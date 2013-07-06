# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides time-based notifications.

import logging
import time

import sg_threading


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class SgTimer(object):
	class TimerEvent(object):
		next_token = 1 # will only be changed from inside SgTimer.add_event() while locked, so no worry about races
		def __init__(self, delay, handler):
			self.when = time.time() + delay
			self.handler = handler
			self.token = SgTimer.TimerEvent.next_token
			SgTimer.TimerEvent.next_token = SgTimer.TimerEvent.next_token + 1

		def __str__(self):
			return '(Event: at %s, token %d)' % (time.ctime(self.when), self.token)

	def __init__(self):
		self.timers = [] # List of TimerEvent objects outstanding
		self.timer_lock = sg_threading.RLock()
		self.timers_changed = sg_threading.Event()
		self.run_thread()

	# public interface
	def add_event(self, delay, handler):
		# takes delay (number of seconds from now), returns token which can be used in cancel_event
		with self.timer_lock:
			event = SgTimer.TimerEvent(delay, handler)
			self.timers.append(event)
			self.timers_changed.set()
		logger.debug('added event %s' % event)
		logger.debug('%d events now in queue' % len(self.timers))
		return event.token

	def cancel_event(self, token):
		removed = [];
		with self.timer_lock:
			removed = filter(lambda event: event.token == token, self.timers)
			self.timers = filter(lambda event: event.token != token, self.timers)
			self.timers_changed.set()
		for event in removed:
			logger.debug('removed event %s' % event)
		logger.debug('%d events now in queue' % len(self.timers))

	# worker thread
	def run_thread(self):
		class TimerDispatcher(sg_threading.Thread):
			def __init__(self, timer):
				super(TimerDispatcher, self).__init__(name = 'time_dispatch')
				self.daemon = True
				self.timer = timer

			def run(self):
				timer = self.timer
				# Loop forever, waiting for either the next known event or a change in the events to wait for.
				# When we wake up, for either reason, look for stuff whose time has come, invoke it, then
				# repeat. It's ok if we wake up too early and nothing is ready.
				while True:
					timer.timers_changed.clear();
					delay = self.timer.time_until_next_event()
					timer.timers_changed.wait(delay)
					timer.invoke_ready()

		self.dispatcher = TimerDispatcher(self)
		self.dispatcher.start()

	def time_until_next_event(self):
		# For now, just a simple O(n) pass over the entire list. If this gets too expensive, we could keep
		# the list sorted by time.
		with self.timer_lock:
			earliest = None
			for event in self.timers:
				if earliest is None or event.when < earliest:
					earliest = event.when
			if earliest is None:
				delay = None
			else:
				delay = event.when - time.time()
				if (delay < 0):
					logger.warning('detected expired event in queue: when=%g now=%g' % (event.when, time.time()))
					delay = 0
		return delay

	def invoke_ready(self):
		# Calculation of which handlers are ready runs with the timer queue locked.
		with self.timer_lock:
			now = time.time()
			ready = [event.handler for event in self.timers if event.when <= now]
			self.timers = [event for event in self.timers if event.when > now]
		# Invocation of the handlers that are ready runs without the lock.
		for handler in ready:
			try:
				handler()
			except:
				logger.exception('exception in timer event handler')
		if ready: # if we did anything
			logger.debug('%d events now in queue' % len(self.timers))


if __name__ == '__main__':
	# Simple unit test
	logger.addHandler(logging.StreamHandler())
	logger.setLevel(logging.DEBUG)
	t = SgTimer()
	def handler(delay):
		print 'I am the %g-sec handler. The time is now %g.' % (delay, time.time())
	tokens = {}
	for delay in [1, 2, 3, 5, 6.5, 6.66, 9]:
		tokens[delay] = t.add_event(delay, lambda delay = delay: handler(delay))
	print '\n\n', 'Added events:', tokens, '\n\n'
	# cancel a few of these
	time.sleep(3)
	t.cancel_event(tokens[5])
	t.cancel_event(tokens[6.66])
	time.sleep(7)
