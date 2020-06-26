# raccoon

Tools for CAN bus forensic analysis. Uses analog or digital samples of CAN bus signals to simulate the following steps that are normally perfomed in hardware:
 - differential comparator with hysteresis,
 - clock synchronization and glitch filtering,
 - bit sampling and transparent stuffing,
 - packet assembly and error detection.

This code was originally developed to help debug CAN bus issues for the [Dark Energy Spectroscopic Instrument (DESI)](https://www.desi.lbl.gov/), which uses 100 separate CAN buses to align 5000 robotic fiber positioners with distant galaxies for any position on the sky.

## Installation

Requires python >= 3.6, numpy and matplotlib:
```
python -m pip install https://github.com/dkirkby/raccoon.git
```

## Usage

Use a `Session` object to ingest, analyze and display raw CAN bus samples. Provide an optional high-level analyzer (HLA) to interpret complete data frames. A suitable HLA for DESI is included:
```
from raccoon.session import Session
from raccoon.desi import desibus

TemperatureRead = Session('TestStand/temp_read_capture.bin', HLA=desibus)
TemperatureRead.overview()
```

### Why the name?

CAN protocol ~ racoon plot
