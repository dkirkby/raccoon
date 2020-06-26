"""Top-level session management.
"""
import numpy as np
import matplotlib.pyplot as plt

from raccoon.saleae import load_analog_binary_v1
from raccoon.util import digitize
from raccoon.can import CANdecoder


class Session(object):

    def __init__(self, filename, threshold=180, hysteresis=50, rate=500000, nchunks=100, HLA=None):
        """Initialize a forensics session using analog traces read from a file.

        Assumes a binary file written with v1.2+ and channels in (CAN_L, CAN_H) pairs for now.
        """
        # Read analog samples.
        analog_samples, self.sampling_period = load_analog_binary_v1(filename)
        nchannels, nsamples = analog_samples.shape
        print(f'Read {nchannels} channels of {nsamples} samples at {1e-6 / self.sampling_period:.1f} MHz.')

        # Pair up CAN signals.
        assert nchannels % 2 == 0
        self.nbus = nchannels // 2
        self.CAN_L = analog_samples[0::2]
        self.CAN_H = analog_samples[1::2]

        # Loop over buses.
        self.chunks = np.linspace(0, nsamples * self.sampling_period, nchunks + 1) - 0.5 * self.sampling_period
        self.overview_data = np.empty((self.nbus, nchunks))
        self.decoder = []
        self.HLA_annotations = [[] for i in range(self.nbus)]
        for bus in range(self.nbus):
            digital_transitions, initial_level = digitize(
                self.CAN_H[bus] - self.CAN_L[bus], threshold, hysteresis, inverted=True)
            digital_transitions = digital_transitions * self.sampling_period
            self.overview_data[bus] = np.histogram(digital_transitions, bins=self.chunks)[0] > 0
            #print(f'Bus {bus} has {len(digital_transitions)} digital transitions.')
            D = CANdecoder(digital_transitions, initial_level, rate=rate)
            self.decoder.append(D)
            D.run()
            if len(D.errors) > 0:
                anybad = np.zeros(len(self.chunks) - 1)
                print(f'Found {len(D.errors)} errors on bus {bus}:')
                for error_type, error_times in D.errors.items():
                    print(f'{len(error_times):6d} {error_type}')
                    bad, _ = np.histogram(error_times / D.rate, bins=self.chunks)
                    anybad += bad
                self.overview_data[bus, anybad > 0] *= -1
            print(f'Decoded {len(D.frames)} frames on bus {bus}.')
            if HLA is not None:
                nbad = 0
                for frame in D.frames:
                    interpreted = HLA(frame)
                    if interpreted is None:
                        print('HLA error:', bus, f'{frame["ID"]:x}', frame['t1'] / D.rate, frame['t2'] / D.rate)
                        nbad += 1
                    else:
                        self.HLA_annotations[bus].append((frame['t1'] / D.rate, frame['t2'] / D.rate, interpreted))
                if nbad > 0:
                    print(f'Unable to interpret {nbad} frames with high-level analyzer.')

    def overview(self, width=8, height=0.5):
        """Display an overview plot of all channels.

        The sampling timeline is divided into ``nchunks`` discrete intervals that are colorcoded
        according to their activity level (yellow = idle, green = valid packets, red = errors).
        """
        vlim = np.max(np.abs(self.overview_data))
        fig = plt.figure(figsize=(width, height * self.nbus))
        plt.imshow(self.overview_data, aspect='auto', origin='upper', interpolation='none',
                   cmap='RdYlGn', vmin=-vlim, vmax=+vlim,
                   extent=[0, 1e3 * self.chunks[-1], self.nbus - 0.5, -0.5])
        plt.yticks(np.arange(self.nbus), [f'BUS{n}' for n in range(self.nbus)])
        plt.xlabel('Elapsed Time [ms]')
        plt.grid()
        plt.tight_layout()

    def detail(self, buses, tstart, tstop,
               analog=True, digital=True, samples=True, annotations=True, HLA=True,
               width=14, height=2):
        """Display a detail plot for selected buses over a limited time interval.
        """
        if tstart < 0 or tstop > self.chunks[-1]:
            raise ValueError('Invalid tstart or tstop.')
        buses = np.atleast_1d(buses)
        nbus = len(buses)
        fig, axes = plt.subplots(nbus, 1, figsize=(width, height * nbus), sharex=True, squeeze=False)
        plt.subplots_adjust(top=0.99, hspace=0.02, left=0.01, right=0.99)
        mul = 1e3
        for ax, bus in zip(axes.flat, buses):
            D = self.decoder[bus]
            lo = int(np.floor(tstart / self.sampling_period))
            hi = int(np.ceil(tstop / self.sampling_period)) + 1
            tvec = mul * np.arange(lo, hi) * self.sampling_period
            ax.set_ylim(-0.05, 1.50)
            ax.set_yticks([])
            if analog:
                rhs = ax.twinx()
                rhs.plot(tvec, self.CAN_H[bus, lo:hi], 'k-', alpha=0.25, lw=1)
                rhs.plot(tvec, self.CAN_L[bus, lo:hi], 'k-', alpha=0.25, lw=1)
                rhs.set_yticks([])
            if digital:
                idx_lo, idx_hi = np.searchsorted(D.dt, [tstart * D.rate, tstop * D.rate])
                segments = [[tstart], D.dt[idx_lo: idx_hi + 1] / D.rate]
                if idx_hi == len(D.dt):
                    segments.append([tstop])
                dt = np.concatenate(segments)
                # Build the waveform of these transitions.
                t_wave = np.stack((dt, dt)).T.reshape(-1)
                x_wave = (D.x0 + idx_lo - 1 + np.arange(len(dt) + 1)) % 2
                x_wave = np.stack((x_wave, x_wave)).T.reshape(-1)[1:-1]
                ax.plot(mul * t_wave, x_wave, c='C0', ls='-', lw=2, alpha=0.5)
            if samples:
                idx_lo, idx_hi = np.searchsorted(D.samples['t'], [tstart * D.rate, tstop * D.rate])
                for i in range(idx_lo, idx_hi):
                    t, level = D.samples[i]['t'], D.samples[i]['level']
                    label = str(level) if level < 2 else ('-' if (level & 2) else 'X')
                    ax.text(mul * t / D.rate, 0.9, label, ha='center', va='top',
                            color='C0', backgroundcolor='w', fontsize=8)
            if annotations:
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
                        (mul * t1[i] / D.rate, 1.05), mul * (t2[i] - t1[i]) / D.rate, 0.2, fill=True, ec='k', fc=color))
                    ax.text(mul * 0.5 * (t1[i] + t2[i]) / D.rate, 1.15, label[i],
                            ha='center', va='center', color='k', fontsize=9, clip_on=True)
            if HLA:
                for (t1, t2, label) in self.HLA_annotations[bus]:
                    if ((t1 > tstart) and (t1 < tstop)) or ((t2 > tstart) and (t2 < tstop)) or ((t1 <= tstart) and (t2 >= tstop)):
                        ax.add_artist(plt.Rectangle(
                            (mul * t1, 1.3), mul * (t2 - t1), 0.2, fill=True, ec='k', fc='skyblue'))
                        ax.text(mul * 0.5 * (t1 + t2), 1.4, label,
                                ha='center', va='center', color='k', fontsize=9, clip_on=True)
            ax.set_xlim(tvec[0], tvec[-1])