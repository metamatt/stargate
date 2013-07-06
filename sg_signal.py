# (c) 2013 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system and friends.
#
# This module provides signal and exception handling.

import logging
import signal
import sys
import threading


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


# signals are process-global, so, so is the state kept by this module.
# No objects, just modue scope.

exit_listeners = []
hup_listeners = []


def init():
	# I want to catch exits due to werkzeug's reloader, which just calls sys.exit(3) directly.
	# So wrap sys.exit:
	real_sys_exit = sys.exit
	def exit_wrapper(exitcode = 0):
		logger.warn("Intercepted sys.exit call")
		_call_listeners(exit_listeners)
		logger.warn("Exiting on sys.exit call")
		real_sys_exit(exitcode)
	sys.exit = exit_wrapper

	# Then install handlers for signals that by default would exit the process.
	def handle_exit_signal(signum, stack_frame):
		logger.warn("Received signal %d" % signum)
		_call_listeners(exit_listeners)
		logger.warn("Exiting on signal %d" % signum)
		real_sys_exit()

	def handle_hup_signal(signum, stack_frame):
		logger.warn("Received signal %d" % signum)
		_call_listeners(hup_listeners)

	signal.signal(signal.SIGHUP, handle_hup_signal)
	signal.signal(signal.SIGINT, handle_exit_signal)
	signal.signal(signal.SIGTERM, handle_exit_signal)
	signal.signal(signal.SIGQUIT, handle_exit_signal)

	# Install global exception handler.
	def excepthook(type, value, traceback):
		name = threading.current_thread().name
		logger.exception('Exception in thread %s' % name)
	sys.excepthook = excepthook


def add_exit_listener(callback):
	exit_listeners.append(callback)

def add_hup_listener(callback):
	hup_listeners.append(callback)

def _call_listeners(listeners):
	for callback in listeners:
		try:
			callback()
		except:
			pass


