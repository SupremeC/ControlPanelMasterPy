#!/usr/bin/env python

import logging
import logging.handlers as handlers

import sys

#     '%(asctime)s-%(msecs)d %(name)s-%(levelname)s-%(message)s')

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s\t%(levelname)s\t%(funcName)10s()\t%(message)s')

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.DEBUG)
stdout_handler.setFormatter(formatter)

file_handler =  handlers.TimedRotatingFileHandler('logs.log', when='D', interval=1, backupCount=30)
# file_handler = logging.FileHandler('logs.log')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stdout_handler)
