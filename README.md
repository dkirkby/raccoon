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
python -m pip install git+https://github.com/dkirkby/raccoon.git
```

## Usage

Use a `Session` object to ingest, analyze and display raw CAN bus samples. Provide an optional high-level analyzer (HLA) to interpret complete data frames. A suitable HLA for [DESI](https://desi.lbl.gov/DocDB/cgi-bin/private/ShowDocument?docid=1710) is included.

For example:
```
from raccoon.session import Session
from raccoon.saleae import load_analog_binary_v1
from raccoon.desi import desibus

# Load binary data captured using Logic v1.2+ from a Saleae analyzer.
samples, period = load_analog_binary_v1('TestStand/PowerDown.bin')

# The binary format does not record channel names so we list them here by hand.
names = 'CAN10L,CAN10H,CAN11L,CAN11H,CAN13L,CAN13H,CAN12L,CAN12H,CAN22L,CAN22H,CAN23L,CAN23H,CAN14L,CAN14H,CAN15L,CAN15H'

# Initialize a forensics session using the DESI protocol for high-level packet analysis.
PowerDown = Session(samples, period, names, HLA=desibus)

# Display an overview plot of bus activity.
PowerDown.overview();
```
This produces the following plot, with YELLOW = bus idle, GREEN = valid frames, RED = errors:
![overview example](https://github.com/dkirkby/raccoon/blob/master/img/overview.png?raw=true)

To show details, zoom in on specific buses and a narrow time interval using `Session.detail(names, tstart, tstop)`. Use optional arguments to control what information is displayed. For example:
```
PowerDown.detail('CAN11', 136.54, 136.70);
```
This displays the following:
![detail example](https://github.com/dkirkby/raccoon/blob/master/img/detail.png?raw=true)

Note the missing ACK bit flagged in red: this should increment the transmitter's error counter but provides more detail than the error counter alone since we now know the source of the error.

### Why the name?

CAN protocol ~ racoon plot
