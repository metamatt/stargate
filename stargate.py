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

import demo
import ra_layout
import ra_repeater

logging.basicConfig(format='%(asctime)s %(levelname)-8s: %(message)s',
                    level = logging.DEBUG)


if __name__ == '__main__':
		# When invoked directly, parse the command line to find hostname and password,
		# then connect, log in, and enter a monitoring loop which just prints system events
		# until killed.
		
		# parse command line
		p = optparse.OptionParser()
		p.add_option('-H', '--hostname', default = 'lutron-radiora', help = 'network hostname for main repeater, default lutron-radiora')
		p.add_option('-U', '--username', default = 'lutron', help = 'username for repeater telnet login')
		p.add_option('-P', '--password', default = 'integration', help = 'password for repeater telnet login')
		p.add_option('-V', '--verbose', action = 'store_true', help = 'enable debug output')
		p.add_option('-D', '--dbcache', help = 'local path to cached DbXmlInfo.xml to use, instead of retrieving it from repeater')
		p.add_option('-S', '--startserver', action = 'store_true', help = 'run webserver mode')
		(options, args) = p.parse_args()
		
		# connect and log in
		layout = ra_layout.RaLayout()
		if options.dbcache:
			layout.read_cached_db(options.dbcache)
		else:
			layout.get_live_db(options.hostname)
		layout.map_db()

		r = ra_repeater.RaRepeater(layout)
		if options.verbose:
			r.set_verbose(True)
		r.connect(options.hostname, options.username, options.password)

		# Canned/hardcoded demos for testing
		#r.enable_monitoring()
		#r.dump_all_levels()
		#r.room_to('11', 75)
		#r.dump_all_on()

		if options.startserver:
			demo.start(r)
