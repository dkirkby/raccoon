"""Generic utilities for working with analog and digital waveform data.
"""
import numpy as np


def digitize(data, threshold, hysteresis, transitions=True, inverted=False):
    """Digitize analog samples.

    Parameters
    ----------
    data: array
        1D array of analog sample values.
    threshold: float
        Threshold value half way between the nominal hi and lo digital values.
    hysteresis: float
        Amount of hysteresis to use during digitization. Defines a deadband
        of this size centered on the threshold, such that samples above or
        below the threshold are considered unambiguous, but samples within
        the deadband retain their previous unambiguous value.
    transitions : bool
        Return the indices of transitions between the lo and hi states when
        True.  Otherwise, return an array of 0,1 values for each sample.

    Returns
    -------
    (array, float) or array
        (indices, level0) when transitions is True or else samples.
    """
    # Identify samples where data is outside the deadband so definitely hi or lo.
    hi = data > threshold + 0.5 * hysteresis
    lo = data < threshold - 0.5 * hysteresis
    # Scan ambiguous segments within the deadband to apply hysteresis.
    enter, level = 0, (data[0] >= threshold)
    for k in np.where(np.diff(~lo & ~hi))[0] + 1:
        if lo[k] or hi[k]:
            # Leaving the deadband from data[k-1] to data[k]
            hi[enter:k] = level
        else:
            # Entering the deadband from data[k-1] to data[k]
            enter, level = k, hi[k - 1]
    if transitions:
        return np.where(np.diff(hi))[0] + 1, (1 if (hi[0] ^ inverted) else 0)
    else:
        digital = ~hi if inverted else hi
        return digital.astype(np.uint8)
