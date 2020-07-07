"""Top-level session management.
"""
import numpy as np
import matplotlib.pyplot as plt

from raccoon.saleae import load_analog_binary_v1
from raccoon.util import digitize
from raccoon.can import CANdecoder


class Session(object):

    def __init__(self, analog_samples, period, names, threshold=180, hysteresis=50, rate=500000, nchunks=100, HLA=None):
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

    def overview(self, width=8, height=0.5, margin=0.6):
        """Display an overview plot of all channels.

        The sampling timeline is divided into ``nchunks`` discrete intervals that are colorcoded
        according to their activity level (yellow = idle, green = valid packets, red = errors).
        """
        nrows, nchunks = self.overview_data.shape
        assert nrows == self.nbus
        fig, ax = plt.subplots(figsize=(width + margin, height * nrows + margin))
        plt.subplots_adjust(left=margin / fig.get_figwidth(), right=1, bottom=margin / fig.get_figheight(), top=1)
        ax.imshow(self.overview_data, origin='upper', interpolation='none',
                  cmap='RdYlGn', vmin=-1, vmax=+1, aspect='auto',
                  extent=[0, 1e3 * self.chunks[-1], self.nbus - 0.5, -0.5])
        ax.set_xlabel('Elapsed Time [ms]')
        ax.grid(which='major', axis='x')
        ax.set_yticks(np.arange(nrows), minor=False)
        ax.set_yticklabels(self.CAN_names)
        ax.set_yticks([0.5], minor=True)
        ax.tick_params(axis='y', which='major', left=False)
        ax.grid(which='minor', axis='y')
        ax.set_ylim(self.nbus - 0.5, -0.5)
        return fig, ax

    def detail(self, names, tstart, tstop,
               analog=True, digital=True, samples=True, annotations=True, HLA=True,
               width=14, height=2):
        """Display a detail plot for selected buses over a limited time interval.
        """
        # Convert from ms to s.
        tstart = 1e-3 * tstart
        tstop = 1e-3 * tstop
        mul = 1e3
        if tstart < 0 or tstop > self.chunks[-1]:
            raise ValueError('Invalid tstart or tstop.')
        names = names.split(',')
        invalid = [N for N in names if N not in self.CAN_names]
        if any(invalid):
            raise ValueError(f'Invalid bus name: {",".join(invalid)}.')
        nchan = len(names)
        fig, axes = plt.subplots(nchan, 1, figsize=(width, height * nchan), sharex=True, squeeze=False)
        plt.subplots_adjust(top=0.99, hspace=0.02, left=0.01, right=0.99)
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
            if analog:
                rhs = ax.twinx()
                rhs.plot(tvec, self.CAN_H[bus][lo:hi], 'k-', alpha=0.25, lw=1)
                rhs.plot(tvec, self.CAN_L[bus][lo:hi], 'k-', alpha=0.25, lw=1)
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
                for (t1, t2, label) in D.HLA_annotations:
                    if (((t1 > tstart * D.rate) and (t1 < tstop * D.rate)) or
                        ((t2 > tstart * D.rate) and (t2 < tstop * D.rate)) or
                        ((t1 <= tstart * D.rate) and (t2 >= tstop * D.rate))):
                        ax.add_artist(plt.Rectangle(
                            (mul * t1 / D.rate, 1.3), mul * (t2 - t1) / D.rate, 0.2, fill=True, ec='k', fc='skyblue'))
                        ax.text(mul * 0.5 * (t1 + t2) / D.rate, 1.4, label,
                                ha='center', va='center', color='k', fontsize=9, clip_on=True)
            ax.set_xlim(tvec[0], tvec[-1])
        return fig, axes
