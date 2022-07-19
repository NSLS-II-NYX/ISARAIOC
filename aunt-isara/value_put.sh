#!/bin/bash

#REM caput IOC0000-000:STATE:onTool "P1"
#REM caput IOC0000-000:STATE:tool "LASER"
#REM caput IOC0000-000:STATE:pos "HOME"

# get, put, getput
caput IOC0000-000:STATE:onTool "P1"
caput IOC0000-000:STATE:tool   "DOUBLE"
caput IOC0000-000:STATE:pos    "SOAK"
caput IOC0000-000:PAR:puck     "3"
caput IOC0000-000:PAR:smpl     "16"
caput IOC0000-000:PAR:smplType "HAMPTON"
