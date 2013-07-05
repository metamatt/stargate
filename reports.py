# (c) 2013 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system and friends.
#
# This module provides reporting (via the notify module) on system events
# and usage.

import logging
import sg_signal


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class SgReporter(object):
	def __init__(self, config, timer, notify):
		self.config = config
		self.timer = timer
		self.notify = notify

		# send startup report
		if self.config.startup:
			self.notify.notify(self.config.startup, 'Stargate is now running', 'Stargate startup')

		# register for shutdown events
		sg_signal.add_exit_listener(self.atexit)

		# register for unhandled exceptions
		# TODO: first we need a mechanism for this, which is sadly nontrivla
		# http://bugs.python.org/issue1230540
		# http://www.bbarrows.com/Python/Logging/BitTorrent/Code/2012/09/24/implementing-exception-logging-in-python.html

		# install timers for interval summaries
		# TODO...

	def atexit(self):
		# send shutdown report
		if self.config.shutdown:
			self.notify.notify(self.config.shutdown, 'Stargate has stopped', 'Stargate shutdown')
