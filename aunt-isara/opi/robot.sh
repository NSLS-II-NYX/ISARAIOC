#!/bin/bash

xset fp+ /usr/share/X11/fonts/100dpi
xset fp+ /usr/share/X11/fonts/75dpi

edm -x -m "device=IOC0000-000" robot.edl
