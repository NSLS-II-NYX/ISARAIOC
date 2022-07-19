#!/bin/bash

xset fp+ /usr/share/X11/fonts/75dpi

export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST="10.0.0.3"

edm -x -m "device=IOC0000-000" /usr/local/epics/opi/robot.edl
