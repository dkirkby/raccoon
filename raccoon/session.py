"""Top-level session management.
"""
import sys
import re

import numpy as np
import matplotlib.pyplot as plt

from raccoon.saleae import load_analog_binary_v1
from raccoon.util import digitize
from raccoon.can import CANdecoder


class Session(object):

    def __init__(self, analog_samples, period, names, threshold=180, hysteresis=50, rate=500000, nchunks=256, HLA=None):
        """Initialize a forensics session using analog traces read from a file.
        """
        self.analog_samples = np.asarray(analog_samples)
        nchannels, nsamples = self.analog_samples.shape
        self.sampling_period = period
        self.names = names.split(',')
        print(f'Created a session with {nchannels} channels of {nsamples} samples at {1e-6 / self.sampling_period:.1f} MHz.')

        # Identify and pair up CAN H/L signals.
        if len(self.names) != len(set(self.names)):
            names, counts = np.unique(self.names, return_counts=True)
            dups = names[counts > 1]
            raise ValueError(f'Found duplicate names: {",".join(dups)}.')
        H_names = set([N[:-1] for N in self.names if N[-1] == 'H'])
        L_names = set([N[:-1] for N in self.names if N[-1] == 'L'])
        if not (H_names == L_names):
            unmatched = H_names ^ L_names
            raise ValueError(f'Found unmatched CAN names: {",".join(unmatched)}.')
        # Use the input order of H signal names to define the bus ordering.
        self.CAN_names = [N[:-1] for N in self.names if N[-1] == 'H']
        self.CAN_H, self.CAN_L = [], []
        self.nbus = len(self.CAN_names)

        # Loop over buses.
        self.chunks = np.linspace(0, nsamples * self.sampling_period, nchunks + 1) - 0.5 * self.sampling_period
        self.overview_data = np.empty((self.nbus, nchunks))
        self.decoder = {}
        for bus in range(self.nbus):
            name = self.CAN_names[bus]
            self.CAN_H.append(self.analog_samples[self.names.index(name + 'H')])
            self.CAN_L.append(self.analog_samples[self.names.index(name + 'L')])
            digital_transitions, initial_level = digitize(
                self.CAN_H[bus] - self.CAN_L[bus], threshold, hysteresis, inverted=True)
            digital_transitions = digital_transitions * self.sampling_period
            self.overview_data[bus] = np.histogram(digital_transitions, bins=self.chunks)[0] > 0
            D = CANdecoder(digital_transitions, initial_level, rate=rate, name=name, HLA=HLA)
            self.decoder[name] = D
            D.run()
            if len(D.errors) > 0:
                anybad = np.zeros(len(self.chunks) - 1)
                print(f'Found {len(D.errors)} errors on {name}:')
                for error_type, error_times in D.errors.items():
                    print(f'{len(error_times):6d} {error_type}')
                    bad, _ = np.histogram(error_times / D.rate, bins=self.chunks)
                    anybad += bad
                self.overview_data[bus, anybad > 0] *= -1
            print(f'Decoded {len(D.frames)} frames on {name}.')
            if D.HLA_errors > 0:
                print(f'HLA was unable to interpret {D.HLA_errors} frames on {name}.')
        # Initialize timestamp parser.
        self.timestamp_format = re.compile('^([+-]\d+)?\[(?:(\w+):)?(-?\d+)\]([+-]\d+)?$')

    def overview(self, width=8, height=0.5, margin=0.6):
        """Display an overview plot of all channels.

        The sampling timeline is divided into ``nchunks`` discrete intervals that are colorcoded
        according to their activity level (yellow = idle, green = valid packets, red = errors).
        """
        nrows, nchunks = self.overview_data.shape
        assert nrows == self.nbus
        fig, ax = plt.subplots(figsize=(width + margin, height * nrows + margin))
        plt.subplots_adjust(left=margin / fig.get_figwidth(), right=0.99, bottom=margin / fig.get_figheight(), top=0.99)
        ax.imshow(self.overview_data, origin='upper', interpolation='none',
                  cmap='RdYlGn', vmin=-1, vmax=+1, aspect='auto',
                  extent=[0, 1e3 * self.chunks[-1], self.nbus - 0.5, -0.5])
        ax.set_xlabel('Elapsed Time [ms]')
        ax.grid(which='major', axis='x')
        ax.set_yticks(np.arange(nrows), minor=False)
        ax.set_yticklabels(self.CAN_names)
        ax.set_yticks(0.5 + np.arange(nrows - 1), minor=True)
        ax.tick_params(axis='y', which='major', left=False)
        ax.grid(which='minor', axis='y')
        ax.set_ylim(self.nbus - 0.5, -0.5)
        return fig, ax

    def list(self, name, first=0, last=None, file=sys.stdout):
        D = self.decoder[name]
        frames = D.frames[first: last]
        hdr = '  N     tstart      tstop    ID    DATA'
        if D.HLA:
            hdr += (' ' * 20) + 'HLA'
        print(hdr, file=file)
        for k, frame in enumerate(frames):
            line = f'{first + k:3d} {1e3 * frame["t1"] / D.rate:10.3f} {1e3 * frame["t2"] / D.rate:10.3f} {frame["ID"]:08X}'
            DLC = frame["DLC"]
            if frame['RTR']:
                data = f'REMOTE DLC={DLC}'
            else:
                data = ','.join([f'{x:02X}' for x in frame["DATA"][:DLC]])
            line += f' {data:23s}'
            if D.HLA:
                line += f' {D.HLA_annotations[first + k][2]}'
            print(line, file=file)

    def timestamp(self, encoded, default_name=None):
        """Decode a timestamp specification.

        The value should either be specified as a floating point value in ms or
        as a string in the format:

        <PRE>[<NAME>:<INDEX>]   or    [<NAME>:<INDEX>]<POST>

        where:
        - <NAME> identifies the bus to use, or use ``default_name`` when omitted.
        - <INDEX> specifies the integer frame index to use, and can be negative.
        - <PRE> and <POST> are signed integer offsets in units of the nominal bit time
        with '+' required, e.g. +1, -2.

        The first form specifies a time relative to the start of the specified frame.
        For example, -2[CAN10:2] is 2 bit times (4us at 0.5Mbs) before the first
        edge (start bit) of the 2nd frame on bus CAN10.

        The second form specifies a time relative to the end of the specified frame.
        For example, [-1]+5 is 5 bit times (10us at 0.5Mbs) after the interframe
        space of the last (index -1) frame on the default bus.

        Parameters
        ----------
        encoded : float or string
            Timestamp value in milliseconds or encoded string.
        default_name : string or None
            Default bus name to use when not specified.

        Returns
        -------
        float
            Timestamp value in seconds.
        """
        try:
            # Convert from ms to s.
            return 1e-3 * float(encoded)
        except ValueError:
            pass
        parsed = self.timestamp_format.match(encoded)
        if not parsed:
            raise ValueError(f'Unable to parse timestamp "{encoded}".')
        pre, name, idx, post = parsed.groups()
        if pre is not None and post is not None:
            raise ValueError(f'Cannot specify pre and post offsets in timestamp: "{encoded}".')
        if pre is None and post is None:
            raise ValueError(f'Must specify either a pre or post offset in timestamp: "{encoded}".')
        name = name or default_name
        try:
            D = self.decoder.get(name)
        except KeyError:
            raise ValueError(f'Invalid bus name "{name}".')
        try:
            frame = D.frames[int(idx)]
        except IndexError:
            raise ValueError(f'Frame index {idx} out of range for {len(D.frames)} frames.')
        if pre is not None:
            return (frame['t1'] + int(pre)) / D.rate
        else:
            return (frame['t2'] + int(post)) / D.rate

    def detail(self, names, tstart, tstop, format='Af', tzero='display', width=14, height=2, margin=0.5):
        """Display a detail plot for selected buses over a limited time interval.

        The tstart and tstop values can either be specified in milliseconds or
        relative to the start or end of any decoded frame.  See meth:`timestamp`
        for details on how frame relative values are encoded.

        The format string is a concatenation of the options to select what to display:
        A: analog traces
        D: digital transitions
        S: sampled binary values, after synchronization and bit stuffing
        F: frame fields (use 'f' to omit text labels)
        H: high-level interpretation (use 'h' to omit text labels)

        Use tzero to configure the plot time origin. The default value of 'display' is
        relative to the left edge of the displayed data.  Otherwise, the value is
        interpreted by :meth:`timestamp`.

        Display time units are selected automatically from s/ms/us depending on the
        displayed range of times.
        """
        names = names.split(',')
        invalid = [N for N in names if N not in self.CAN_names]
        if any(invalid):
            raise ValueError(f'Invalid bus name: {",".join(invalid)}.')
        nchan = len(names)
        # Decode timestamps.
        default_name = names[0]
        tstart = self.timestamp(tstart, default_name)
        tstop = self.timestamp(tstop, default_name)
        if tstart < 0:
            raise ValueError(f'Invalid tstart < 0: {tstart}.')
        if tstop > self.chunks[-1]:
            raise ValueError(f'Invalid tstop > {self.chunks[-1]:.3f}: {tstop}.')
        # Select display units based on the display range.
        trange = tstop - tstart
        if trange > 1:
            mul, unit = 1, 's'
        elif trange > 0.001:
            mul, unit = 1e3, 'ms'
        else:
            mul, unit = 1e6, 'us'
        # Select display time origin.
        if tzero is 'display':
            tzero = tstart
        else:
            tzero = self.timestamp(tzero, default_name)
        tzero *= mul
        # Initialize plots.
        fig, axes = plt.subplots(nchan, 1, figsize=(width, height * nchan + margin), sharex=True, squeeze=False)
        plt.subplots_adjust(top=0.99, hspace=0.02, left=0.01, right=0.99, bottom=margin / fig.get_figheight())
        for ax, name in zip(axes.flat, names):
            bus = self.CAN_names.index(name)
            D = self.decoder[name]
            lo = int(np.floor(tstart / self.sampling_period))
            hi = int(np.ceil(tstop / self.sampling_period)) + 1
            tvec = mul * np.arange(lo, hi) * self.sampling_period
            ax.set_ylim(-0.05, 1.50)
            ax.set_yticks([])
            ax.text(0.01, 0.01, name, transform=ax.transAxes, ha='left', va='bottom',
                    fontsize=14, fontweight='bold', color='k')
            if 'A' in format:
                rhs = ax.twinx()
                rhs.plot(tvec - tzero, self.CAN_H[bus][lo:hi], 'k-', alpha=0.25, lw=1)
                rhs.plot(tvec - tzero, self.CAN_L[bus][lo:hi], 'k-', alpha=0.25, lw=1)
                rhs.set_yticks([])
            if 'D' in format:
                idx_lo, idx_hi = np.searchsorted(D.dt, [tstart * D.rate, tstop * D.rate])
                segments = [[tstart], D.dt[idx_lo: idx_hi + 1] / D.rate]
                if idx_hi == len(D.dt):
                    segments.append([tstop])
                dt = np.concatenate(segments)
                # Build the waveform of these transitions.
                t_wave = np.stack((dt, dt)).T.reshape(-1)
                x_wave = (D.x0 + idx_lo - 1 + np.arange(len(dt) + 1)) % 2
                x_wave = np.stack((x_wave, x_wave)).T.reshape(-1)[1:-1]
                ax.plot(mul * t_wave - tzero, x_wave, c='C0', ls='-', lw=2, alpha=0.5)
            if 'S' in format:
                idx_lo, idx_hi = np.searchsorted(D.samples['t'], [tstart * D.rate, tstop * D.rate])
                for i in range(idx_lo, idx_hi):
                    t, level = D.samples[i]['t'], D.samples[i]['level']
                    label = str(level) if level < 2 else ('-' if (level & 2) else 'X')
                    ax.text(mul * t / D.rate - tzero, 0.9, label, ha='center', va='top',
                            color='C0', backgroundcolor='w', fontsize=8)
            if 'F' in format.upper():
                t1, t2, label = D.annotations['t1'], D.annotations['t2'], D.annotations['label']
                t1_in = (t1 > tstart * D.rate) & (t1 < tstop * D.rate)
                t2_in = (t2 > tstart * D.rate) & (t2 < tstop * D.rate)
                over = (t1 <= tstart * D.rate) & (t2 >= tstop * D.rate)
                for i in np.where(t1_in | t2_in | over)[0]:
                    if label[i].startswith('DATA'):
                        color = 'cyan'
                    elif label[i].startswith('ID'):
                        color = 'yellow'
                    elif label[i].startswith('!'):
                        color = 'red'
                    else:
                        color = 'lightgray'
                    ax.add_artist(plt.Rectangle(
                        (mul * t1[i] / D.rate - tzero, 1.05), mul * (t2[i] - t1[i]) / D.rate, 0.2,
                        fill=True, ec='k', fc=color))
                    if 'F' in format:
                        ax.text(mul * 0.5 * (t1[i] + t2[i]) / D.rate - tzero, 1.15, label[i],
                                ha='center', va='center', color='k', fontsize=9, clip_on=True)
            if 'H' in format.upper():
                for (t1, t2, label) in D.HLA_annotations:
                    if (((t1 > tstart * D.rate) and (t1 < tstop * D.rate)) or
                        ((t2 > tstart * D.rate) and (t2 < tstop * D.rate)) or
                        ((t1 <= tstart * D.rate) and (t2 >= tstop * D.rate))):
                        ax.add_artist(plt.Rectangle(
                            (mul * t1 / D.rate - tzero, 1.3), mul * (t2 - t1) / D.rate, 0.2,
                            fill=True, ec='k', fc='skyblue'))
                        if 'H' in format:
                            ax.text(mul * 0.5 * (t1 + t2) / D.rate - tzero, 1.4, label,
                                    ha='center', va='center', color='k', fontsize=9, clip_on=True)
            ax.set_xlim(mul * tstart - tzero, mul * tstop - tzero)
            ax.set_xlabel(f'Time [{unit}]')
            if (tzero > mul * tstart) and (tzero < mul * tstop):
                ax.axvline(0, ls=':', c='k', alpha=0.5, lw=2)
        return fig, axes
