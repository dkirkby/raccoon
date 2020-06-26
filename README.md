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

Use a `Session` object to ingest, analyze and display raw CAN bus samples. Provide an optional high-level analyzer (HLA) to interpret complete data frames. A suitable HLA for [DESI](https://desi.lbl.gov/DocDB/cgi-bin/private/ShowDocument?docid=1710) is included.

For example:
```
from raccoon.session import Session
from raccoon.desi import desibus

PowerDown = Session('TestStand/PowerDown.bin', HLA=desibus)
PowerDown.overview()
```
This produces the following plot, with YELLOW = bus idle, GREEN = valid frames, RED = errors:
![overview example](https://github.com/dkirkby/raccoon/blob/master/img/overview.png?raw=true)

To show details, zoom in on specific buses and a narrow time interval using `Session.detail(buses, tstart, tstop)`. Use optional arguments to control what information is displayed. For example:
```
PowerDown.detail(0, tstart=0.09996, tstop=0.1002)
```
This displays:
![detail example](https://github.com/dkirkby/raccoon/blob/master/img/detail.png?raw=true)


### Why the name?

CAN protocol ~ racoon plot
