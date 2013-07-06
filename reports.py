# (c) 2013 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system and friends.
#
# This module provides reporting (via the notify module) on system events
# and usage.

import logging
import sg_signal
import traceback


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class SgReporter(object):
	def __init__(self, config, sg_timer, sg_notify):
		self.config = config
		self.sg_timer = sg_timer
		self.sg_notify = sg_notify

		# send startup report
		if self.config.startup:
			self.sg_notify.notify(self.config.startup, 'Stargate is now running', 'Stargate startup')

		# register for shutdown events
		sg_signal.add_exit_listener(self.on_exit)

		# register for logger.exception
		sg_signal.add_exception_listener(self.on_exception)

		# install timers for interval summaries
		# TODO...

	def on_exception(self):
		if self.config.exception:
			report = traceback.format_exc();
			self.sg_notify.notify(self.config.exception, report, 'Stargate exception report')

	def on_exit(self):
		# send shutdown report
		if self.config.shutdown:
			self.sg_notify.notify(self.config.shutdown, 'Stargate has stopped', 'Stargate shutdown')
