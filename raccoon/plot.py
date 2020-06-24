"""Plotting utilities.
"""
import matplotlib.pyplot as plt

import raccoon.can


def plot(self, t_before=40, t_after=20, glitches=True, levels=True, annotations=True, ax=None):
    """Plot transitions centered on the current cursor position.
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(16, 2.5))
    t_cursor = self.sample_t[self.sample_k]
    t_lo = t_cursor - t_before
    t_hi = t_cursor + t_after
    ax.set_xlim(t_lo, t_hi)
    ax.set_ylim(-0.05, 1.25)
    ax.set_yticks([])
    ax.set_xlabel(f'Sample # [{1e6/self.rate:.1f}us]')
    ax.axvline(self.dt[self.cursor], ls='-', c='C1')
    ax.axvline(t_cursor, ls=':', c='C0')
    # Find transitions spanning this window.
    idx_lo, idx_hi = np.searchsorted(self.dt, [t_lo, t_hi])
    idx_lo = max(0, idx_lo - 1)
    dt = self.dt[idx_lo: idx_hi + 1]
    # Build the waveform of these transitions.
    t_wave = np.stack((dt, dt)).T.reshape(-1)
    x_wave = (self.x0 + idx_lo + np.arange(len(dt) + 1)) % 2
    x_wave = np.stack((x_wave, x_wave)).T.reshape(-1)[1:-1]
    ax.plot(t_wave, x_wave, 'k-', lw=1)
    if glitches:
        t_rel = np.round(np.arange(t_lo - t_cursor, t_hi - t_cursor + 1), 0)
        idx_edge = np.searchsorted(dt, t_cursor + t_rel)
        n_glitch = np.diff(idx_edge)
        if np.any(n_glitch > 1):
            for k in np.where(n_glitch > 1)[0]:
                # centered on where the transition is nominally expected.
                t = t_cursor + t_rel[k + 1] - 0.5
                #t = dt[idx_edge[k]]
                # centered on the actual first and last transitions between samples.
                ##t = 0.5 * (dt[idx_edge[k]] + dt[idx_edge[k] + n_glitch[k] - 1])
                ax.text(t, 0.1, str(n_glitch[k]), ha='center', va='bottom',
                        color='r', backgroundcolor='w', fontsize=11)
    if levels:
        for t, x, u in zip(self.sample_t, self.sample_level, self.sample_unstuffed):
            if t > t_lo and t < t_hi:
                ax.text(t, 0.9, '-' if u else str(x), ha='center', va='top',
                        color='C0', backgroundcolor='w', fontsize=11)
    if annotations:
        for (t1, t2, label, color) in self.annotations:
            if (t1 > t_lo and t1 < t_hi) or (t2 > t_lo and t2 < t_hi):
                ax.add_artist(plt.Rectangle((t1, 1.05), t2 - t1, 0.2, fill=True, ec='k', fc=color))
                ax.text(0.5 * (t1 + t2), 1.1, label, ha='center', va='bottom',
                        color='k', fontsize=11)
    return ax

raccoon.can.CANdecoder.plot = plot
