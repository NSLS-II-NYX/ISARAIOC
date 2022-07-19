#!/usr/bin/env python
import os
import logging
import sys
import argparse

# Twisted boiler-plate code.
from twisted.internet import gireactor
gireactor.install()
from twisted.internet import reactor

# add the project to the python path and inport it
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from softdev import log
from myioc import ioc

# Setup single argument for verbose logging
parser = argparse.ArgumentParser(description='Run IOC Application')
parser.add_argument('-v', action='store_true', help='Verbose Logging')
args = parser.parse_args()

if __name__== '__main__':
    if args.v:
        log.log_to_console(logging.DEBUG)
    else:
        log.log_to_console(logging.INFO)

    # initialize App
    app = ioc.MyIOCApp('APP0000-01')

    # make sure app is properly shutdown
    reactor.addSystemEventTrigger('before', 'shutdown', app.shutdown)

    # run main-loop
    reactor.run()
