"""CAN bus protocol decoding.
"""
import collections
import numpy as np


class CANerror(RuntimeError):
    """First ctor arg is a string specifying the generic error type.
    Any subsequent args provide details for a specific error.
    """
    pass


class CANdecoder(object):

    def __init__(self, times, x0, t0=0, rate=500000, name=None, HLA=None):
        """Initialize a CAN protocol decoder to parse a sequence of digital transitions.

        Parameters
        ----------
        t0 : float
            Initial timestamp.
        x0 : int
            Initial logic level, must be zero or one.
        times : array
            Array of timestamps for logic level transitions.
        rate : float
            CAN data rate in bits per second.
        name : str or None
            Optional name identifying this bus.
        HLA : callable or None
            Optional high-level analysis interpreter to apply to all valid packets.
            Will be called with a single-row numpy recarray with fields: t1, t2,
            IDE, RTR, ID, DLC, DATA.  Returns a descriptive string if the packet was
            successfully interpreted, or else returns None.
        """
        if x0 not in (0, 1):
            raise ValueError(f'Expected x0 in (0,1) but got {x0}')
        self.x0 = x0
        self.rate = rate
        self.dt = rate * (np.asarray(times) - t0)
        self.crc_poly = np.uint16(0x4599)
        self.crc_mask = np.uint16(0x7fff)
        self.MAX_ANNOTATION_LENGTH = 12
        self.name = name
        self.HLA = HLA

    def run(self):
        self.cursor = 0
        self.samples = []
        self.frames = []
        self.annotations = []
        self.errors = collections.defaultdict(list)
        self.sample()
        while True:
            try:
                self.decode()
            except CANerror as e:
                t_error = self.sample_t[self.sample_k - 1]
                self.errors[e.args[0]].append(t_error)
                self.annotations.append((t_error - 0.5, t_error + 0.5, '!'))
                try:
                    self.advance()
                except StopIteration:
                    break
            except StopIteration:
                break
        # Convert results to numpy arrays.
        self.samples = np.array(self.samples, dtype=[
            ('t', np.float32), ('level', np.uint8)])
        for k, v in self.errors.items():
            self.errors[k] = np.array(v, np.float32)
        self.annotations = np.array(self.annotations, dtype=[
            ('t1', np.float32), ('t2', np.float32), ('label', np.unicode_, self.MAX_ANNOTATION_LENGTH)])
        self.frames = np.array(self.frames, dtype=[
            ('t1', np.float32), ('t2', np.float32), ('IDE', np.uint8), ('RTR', np.uint8),
            ('ID', np.uint32), ('DLC', np.uint8), ('DATA', np.uint8, 8)])
        self.HLA_annotations = []
        self.HLA_errors = 0
        if self.HLA is not None:
            for frame in self.frames:
                interpreted = self.HLA(frame)
                if interpreted is None:
                    interpreted = '???'
                    self.HLA_errors += 1
                self.HLA_annotations.append((frame['t1'], frame['t2'], interpreted))


    @property
    def cursor(self):
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        if value >= len(self.dt):
            raise StopIteration()
        self._cursor = value

    def sample(self, nbits=160, max_glitch=0.1):
        """Sample the next nbits starting from the next transition.

        The default nbits is the maximum possible length of an extended data packet, including
        bit stuffing and interframe space.

        After calling this method, a frame of nbits samples starting with the currrent
        transition ``self.cursor`` are captured and indexed with ``self.k``
        """
        current_level = (self.x0 + self.cursor) % 2
        if current_level == 0:
            # Advance to the next bus-idle state.
            self.cursor += 1
        # Skip over any glitches during the bus idle state.
        while (self.cursor < len(self.dt) - 2) and (self.dt[self.cursor + 1] - self.dt[self.cursor] < max_glitch):
            self.cursor += 2
        # Calculate the centers of the next nbits when we should sample the level.
        self.sample_t = self.dt[self.cursor] + 0.5 + np.arange(nbits)
        # How many transitions before the last sample?
        last = np.searchsorted(self.dt, self.sample_t[-1])
        # Align transitions to samples.
        self.sample_idx = np.searchsorted(self.dt[self.cursor:self.cursor + last + 1], self.sample_t)
        # Calculate the corresponding levels.
        self.sample_level = (self.x0 + self.cursor + self.sample_idx) % 2
        # Initialize access via nextbit() and nextfield().
        self.sample_k = 0
        self.last_level = None
        self.num_repeats = 0
        self.sample_nbits = nbits

    def nextbit(self, unstuff=True, update_crc=True):
        """Return the next sampled bit with stuff bits optionally removed.

        Parameters
        ----------
        unstuff : bool
            Remove stuff bits inserted by the transmitter. This should normally
            always be done except when processing the last 10 bits of a frame,
            consisting of the CRC delimiter, ACK, ACK Delimeter and 7 EOF bits.
        update_crc : bool
            Update the running CRC calculation. This should normally be done
            for all bits of a packet up to the CRC field.
        """
        if self.sample_k >= self.sample_nbits:
            raise RuntimeError('All sample bits already consumed.')
        x = self.sample_level[self.sample_k]
        self.samples.append((self.sample_t[self.sample_k], x))
        self.sample_k += 1
        if unstuff and (x == self.last_level):
            self.num_repeats += 1
            if self.num_repeats == 5:
                xstuffed = self.sample_level[self.sample_k]
                if xstuffed == self.last_level:
                    # Set bit-2 to flag invalid stuffed bit.
                    self.samples.append((self.sample_t[self.sample_k], xstuffed | 4))
                    raise CANerror('Error frame detected', f'starts at bit {self.sample_k}')
                else:
                    # Set bit-1 to flag valid stuffed bit.
                    self.samples.append((self.sample_t[self.sample_k], xstuffed | 2))
                    self.sample_k += 1
                    self.last_level = xstuffed
                    self.num_repeats = 1
        else:
            self.last_level = x
            self.num_repeats = 1
        if update_crc:
            self.crc <<= 1
            if (self.crc >> 15) ^ x:
                self.crc ^= self.crc_poly
            self.crc &= self.crc_mask
        return x

    def nextfield(self, nbits, label=None, unstuff=True, update_crc=True):
        """Return the next nbits as an unsigned integer field read MSB first.

        Set label to store an annoation for this field to display using :meth:`plot`.

        See :meth:`nextbit` for a description of the last two parameters.
        """
        value = 0
        start_k = self.sample_k
        for i in range(nbits):
            value = (value << 1) | self.nextbit(unstuff, update_crc)
        if label is not None:
            t_lo = self.sample_t[start_k] - 0.5
            t_hi = self.sample_t[self.sample_k] - 0.5
            formatted = label.format(value=value)
            if len(formatted) > self.MAX_ANNOTATION_LENGTH:
                print('WARNING: truncating annotation label "{formatted}".')
            self.annotations.append((t_lo, t_hi, formatted[:self.MAX_ANNOTATION_LENGTH]))
        return value

    def decode(self):
        self.crc = np.uint16(0)
        if self.nextbit() != 0:
            raise CANerror('Invalid start of frame (SOF) bit')
        ident = self.nextfield(11, label='IDA={value:03X}')
        RTR = self.nextbit()
        IDE = self.nextbit()
        if IDE == 1:
            if RTR == 0:
                raise CANerror('Invalid substitute remote request (SSR) bit')
            # Decode extended frame format.
            ident = (ident << 18) | self.nextfield(18, label='IDB={value:05X}')
            RTR = self.nextbit()
            r1 = self.nextbit() # Either value allowed
        r0 = self.nextbit() # Either value allowed
        DLC = self.nextfield(4, label='DLC={value:d}')
        data = np.zeros(8, np.uint8)
        if RTR == 0:
            for i in range(DLC):
                data[i] = self.nextfield(8, label=f'DATA{i}={{value:02X}}')
        CRC = self.nextfield(15, update_crc=False, label='CRC={value:04X}')
        if CRC != self.crc:
            raise CANerror('CRC failed', f'got {CRC}={CRC:b} but expected {self.crc}={self.crc:b}')
        CRCdelim = self.nextbit(unstuff=False, update_crc=False)
        if CRCdelim != 1:
            raise CANerror('Invalid CRC delimiter bit')
        ACK = self.nextbit(unstuff=False, update_crc=False)
        if ACK == 1:
            raise CANerror('Missing ACK from any receiver')
        ACKdelim = self.nextbit(unstuff=False, update_crc=False)
        if ACKdelim != 1:
            raise CANerror('Invalid ACK delimiter bit')
        EOF = self.nextfield(7, label='EOF', unstuff=False, update_crc=False)
        if EOF != 0x7f:
            raise CANerror('Invalid end of frame (EOF)')
        IFS = self.nextfield(3, label='IFS', unstuff=False, update_crc=False)
        if IFS != 0x7:
            raise CANerror('Invalid interframe space (IFS)')
        # If we get here, we have successfully decoded a data or remote frame.
        tstart = self.sample_t[0] - 0.5
        tstop = self.sample_t[self.sample_k - 1] + 0.5
        self.frames.append((tstart, tstop, IDE, RTR, ident, DLC, data))
        self.advance()

    def advance(self):
        # Move the cursor to the next transition edge.
        self.cursor += self.sample_idx[self.sample_k - 1]
        # Sample the next potential packet.
        self.sample()
