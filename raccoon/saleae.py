"""Support functions for the Saleae family of logic analyzers
"""
import struct

import numpy as np


def load_analog_binary_v1(filename):
    """Load analog traces stored in the binary format by Logic 1.2.0+

    The format is documented at
    https://support.saleae.com/faq/technical-faq/data-export-format-analog-binary

    Returns (data, period) where data is a numpy array of 32-bit little-endian
    floats of shape (nchannels, nsamples) and period is the sampling period in seconds.
    """
    with open(filename, 'rb') as f:
        nsamples, nchannels, period = struct.unpack('<QId', f.read(20))
        if nchannels > 16:
            raise RuntimeError(f'Invalid nchannels={nchannels}. Are you sure this is binary analog data from v1.2.0+?')
        if period < 1 / 50e6 or period > 1:
            raise RuntimeError(f'Invalid period={period}. Are you sure this is binary analog data from v1.2.0+?')
        data = np.fromfile(f, dtype=np.dtype('<f'), count=nsamples * nchannels).reshape(nchannels, nsamples)
    return data, period
