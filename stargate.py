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


def str_to_loglevel(loglevel_str):
	loglevel = getattr(logging, loglevel_str.upper(), None)
	if not isinstance(loglevel, int):
		raise ValueError('Invalid log level: %s' % loglevel_str)
	return loglevel


if __name__ == '__main__':
	# parse command line
	p = optparse.OptionParser()
	p.add_option('-c', '--config', default = 'config.yaml', help = 'configuration file')
	(options, args) = p.parse_args()
	
	# read yaml config file
	config_file = open(options.config)
	config = yaml.safe_load(config_file)
	config_file.close()
	
	# configure logging
	logger = logging.getLogger()
	global_loglevel = str_to_loglevel(config['logging']['level'])
	logger.setLevel(global_loglevel)
	log_formatter = logging.Formatter('%(asctime)s %(threadName)-12s %(levelname)-8s: %(message)s')
	# log to file
	logfile_formatstr = config['logging']['logfile']
	logfile_params = { 'pid': os.getpid() }
	logfile = logfile_formatstr % logfile_params
	file_loghandler = logging.FileHandler(logfile)
	file_loghandler.setLevel(global_loglevel)
	file_loghandler.setFormatter(log_formatter)
	logger.addHandler(file_loghandler)
	# log to console (with possibly reduced level)
	if config['logging'].has_key('console_level'):
		console_loglevel = str_to_loglevel(config['logging']['console_level'])
		assert console_loglevel >= global_loglevel
	else:
		console_loglevel = global_loglevel
	console_loghandler = logging.StreamHandler()
	console_loghandler.setLevel(console_loglevel)
	console_loghandler.setFormatter(log_formatter)
	logger.addHandler(console_loghandler)
	# configure module loglevels
	for key in config['logging']:
		if key[:6] == 'level.':
			module = key[6:]
			module_logger = logging.getLogger(module)
			module_loglevel = str_to_loglevel(config['logging'][key])
			module_logger.setLevel(module_loglevel)
	
	# connect and log in
	# XXX: Werkzeug/Flask has a debugger with a reloader feature which if
	# enabled will cause it to immediately respawn another copy of this process;
	# the upshot is all this code runs twice and we only want it to run once.
	# Figure out if we're the parent process which will exist only to watch over
	# reloadable children, and if so, avoid any heavy lifting.
	if config['server']['webdebug'] and not os.environ.get('WERKZEUG_RUN_MAIN'):
		logger.warning('startup: pid %d is the werkzeug reloader' % os.getpid())
		house = None
	else:
		logger.warning('startup: pid %d is the active werkzeug' % os.getpid())
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
