"""Support functions for the Saleae family of logic analyzers
"""
import struct
from pathlib import Path

import numpy as np


def load_analog_binary_v1(filename):
    """Load analog traces stored in the binary format by Logic 1.2.0+

    The format is documented at
    https://support.saleae.com/faq/technical-faq/data-export-format-analog-binary

    Returns (data, period) where data is a numpy array of 32-bit floats
    of shape (nchannels, nsamples) and period is the sampling period in seconds.
    """
    with open(filename, 'rb') as f:
        nsamples, nchannels, period = struct.unpack('<QId', f.read(20))
        if nchannels > 16:
            raise RuntimeError(f'Invalid nchannels={nchannels}. Are you sure this is binary analog data from v1.2.0+?')
        if period < 1 / 50e6 or period > 1:
            raise RuntimeError(f'Invalid period={period}. Are you sure this is binary analog data from v1.2.0+?')
        data = np.fromfile(f, dtype=np.dtype('<f'), count=nsamples * nchannels).reshape(nchannels, nsamples).astype('=f')
    return data, period


def load_analog_binary_v2(dirname):
    """Load analog traces stored in the binary format by Logic 2.x

    The format is documented at
    https://support.saleae.com/faq/technical-faq/binary-export-format-logic-2

    Returns (data, period) where data is a numpy array of 32-bit floats
    of shape (nchannels, nsamples) and period is the sampling period in seconds.
    """
    period = None
    filenames = list(Path(dirname).glob('*_*.bin'))
    # Assume only analog channels are present.
    nchannels = len(filenames)
    for filename in filenames:
        stem = filename.stem
        idx = stem.index('_')
        if stem[:idx] != 'analog':
            # Do not allow any digital channels for now.
            raise RuntimeError(f'Found unexpected file: {filename}.')
        chan = int(stem[idx + 1:])
        with open(filename, 'rb') as f:
            identifier = f.read(8)
            if identifier != b"<SALEAE>":
                raise RuntimeError(f'File has invalid header id: {filename}.')
            version, datatype = struct.unpack('=ii', f.read(8))
            if version != 0:
                raise RuntimeError(f'File has invalid version: {filename}.')
            if datatype != 1:
                raise RuntimeError(f'File has invalid datatype: {filename}.')
            begin_time, sample_rate, downsample, nsamples = struct.unpack('=dqqq', f.read(32))
            if period is None:
                period = downsample / sample_rate
                data = np.empty((nchannels, nsamples), np.float32)
            elif downsample / sample_rate != period:
                raise RuntimeError('Channels not saved with consistent sampling rate.')
            elif nsamples != data.shape[1]:
                raise RuntimeError('Channels not saved with same number of samples.')
            data[chan] = np.fromfile(f, dtype=np.dtype('<f'), count=nsamples)
    return data, period
