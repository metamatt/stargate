# (c) 2013 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system and friends.
#
# This module provides signal and exception handling.
#
# Clients can request notification of various signals, as well as calls
# to logger.exception() and sys.exit().
#
# We also install a sys.excepthook that makes sure unhandled exceptions
# go through the logger, and thus to subscribers of add_exception_listener.

import logging
import signal
import sys
import threading
import traceback


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


# signals are process-global, so, so is the state kept by this module.
# No objects, just modue scope.

exit_listeners = []
hup_listeners = []
exception_listeners = []


def init():
	# Monkey-patch to wrap sys.exit
	# (The special motivation for this is werkzeug's debugging reloader, which
	# just calls sys.exit(3) directly. But it's good if nothing can sys.exit
	# without us knowing.)
	real_sys_exit = sys.exit
	def exit_wrapper(*args, **kwargs):
		logger.warn("Intercepted sys.exit call")
		_call_listeners(exit_listeners)
		logger.warn("Exiting on sys.exit call")
		real_sys_exit(*args, **kwargs)
	sys.exit = exit_wrapper

	# Then install handlers for signals that by default would exit the process.
	# (It turns out that Werkzeug also installs its own SIGTERM handler that calls
	# sys.exit, so SIGTERM may follow the path above instead of this one, depending
	# on our initialization order. No matter; they do the same thing.)
	def handle_exit_signal(signum, stack_frame):
		logger.warn("Received signal %d" % signum)
		_call_listeners(exit_listeners)
		logger.warn("Exiting on signal %d" % signum)
		real_sys_exit()

	signal.signal(signal.SIGINT, handle_exit_signal)
	signal.signal(signal.SIGTERM, handle_exit_signal)
	signal.signal(signal.SIGQUIT, handle_exit_signal)

	# And install SIGHUP handler.
	def handle_hup_signal(signum, stack_frame):
		logger.warn("Received signal %d" % signum)
		_call_listeners(hup_listeners)

	signal.signal(signal.SIGHUP, handle_hup_signal)

	# Add a logging handler which gets and forwards calls to logger.exception
	rootLogger = logging.getLogger()
	class ExceptionForwardingHandler(logging.NullHandler):
		def handle(self, record):
			if record.exc_info:
				_call_listeners(exception_listeners)
	rootLogger.addHandler(ExceptionForwardingHandler())

	# Install global exception handler. We don't let client code hook this itself,
	# but we forward exceptions to logger.exception which we do let clients hook.
	# (Note that this would apply only to MainThread with naive use of threading.Thread,
	# but sg_threading.Thread makes sure it gets called in child threads too.)
	def excepthook(type, value, traceback):
		name = threading.current_thread().name
		logger.exception('Exception in thread %s' % name)
	sys.excepthook = excepthook


def add_exit_listener(callback):
	exit_listeners.append(callback)

def add_hup_listener(callback):
	hup_listeners.append(callback)

def add_exception_listener(callback):
	exception_listeners.append(callback)

def _call_listeners(listeners):
	for callback in listeners:
		try:
			callback()
		except:
			logger.error('Exception during signal handler:\n%s' % traceback.format_exc())
