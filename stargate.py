#! /usr/bin/env python
#
# Simple test module for Lutron RadioRa2 network integration.
# Author: matt@ginzton.net
#
# Bugs:
# - simple, incomplete
# - should reconnect automatically if connection drops

import logging
import optparse
import os
import yaml

import demo
import ra_house
import ra_layout
import ra_repeater


if __name__ == '__main__':
		# parse command line
		p = optparse.OptionParser()
		p.add_option('-c', '--config', default = 'config.yaml', help = 'configuration file')
		(options, args) = p.parse_args()
		
		# read yaml config file
		config_file = open(options.config)
		config = yaml.safe_load(config_file)
		config_file.close()
		
		# initialize logging
		loglevel_str = config['logging']['loglevel']
		loglevel = getattr(logging, loglevel_str.upper(), None)
		if not isinstance(loglevel, int):
			raise ValueError('Invalid log level: %s' % loglevel_str)
		logfile_formatstr = config['logging']['logfile']
		logfile_params = { 'pid': os.getpid() }
		logfile = logfile_formatstr % logfile_params
		logger = logging.getLogger()
		logger.setLevel(loglevel)
		log_formatter = logging.Formatter('%(asctime)s %(threadName)-12s %(levelname)-8s: %(message)s')
		file_loghandler = logging.FileHandler(logfile)
		file_loghandler.setLevel(loglevel)
		file_loghandler.setFormatter(log_formatter)
		logger.addHandler(file_loghandler)
		console_loghandler = logging.StreamHandler()
		console_loghandler.setLevel(logging.INFO)
		console_loghandler.setFormatter(log_formatter)
		logger.addHandler(console_loghandler)
		
		# connect and log in
		repeater_config = config['repeater']
		layout = ra_layout.RaLayout(ignore_devices = repeater_config['layout']['ignore_keypads'])
		if repeater_config.has_key('cached_database'):
			layout.read_cached_db(repeater_config['cached_database'])
		else:
			layout.get_live_db(repeater_config['hostname'])
		layout.map_db()

		repeater = ra_repeater.RaRepeater()
		repeater.connect(repeater_config['hostname'], repeater_config['username'], repeater_config['password'])
		
		house = ra_house.House(repeater, layout)

		# run the web app
		demo.start(house, **config['server'])
