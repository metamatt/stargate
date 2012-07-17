# This module handles the TCP connection to the repeater,
# and provides an interface for getting/setting load status
# and sending commands to/from Ra2 devices.
#
# Rewrite in progress, after which, this should say:
#
# This module handles the TCP connection to the repeater,
# and listens to it in monitor mode to build a cache of
# device state for the entire system. It provides a low-level
# interface for querying and changing the state of outputs
# and devices.

import re
import select
import socket
import time
import threading

# states we recognize in repeater listener
STATE_FRESH_CONNECTION, STATE_PROCESSING, STATE_WANT_LOGIN, STATE_WANT_PASSWORD, STATE_READY = range(5)
# repeater responses that are all she wrote, and won't be followed by CRLF
ra_prompts = set(['login: ', 'password: ', 'GNET> '])
CRLF = '\r\n'

class OutputCache(object):
	# Low-level cache of last seen level for each device (output, button, led)
	repeater = None

	def __init__(self):
		self.output_levels = {}
		self.button_states = {}
		self.led_states = {}
	
	def watch_output(self, output_iid):
		self.output_levels[output_iid] = 'stale'
	
	def watch_device(self, device_iid, button_cids, led_cids):
		button = self.button_states[device_iid] = dict()
		for cid in button_cids:
			button[cid] = 'stale'
		led = self.led_states[device_iid] = dict()
		for cid in led_cids:
			led[cid] = 'stale'

	def record_output_level(self, output_iid, level):
		# should be called only by RaRepeater.repeaterReply()
		print "record_output_level: output %d level %d" % (output_iid, level)
		self.output_levels[output_iid] = level

	def get_output_level(self, output_iid):
		level = self.output_levels[output_iid]
		while level == 'stale':
			self._refresh_output(output_iid)
			time.sleep(0.1)
			level = self.output_levels[output_iid]
		return level

	def record_button_state(self, device_iid, button_cid, state):
		# should be called only by RaRepeater.repeaterReply()
		print "record_button_state: device %d button %d state %d" % (device_iid, button_cid, state)
		self.button_states[device_iid][button_cid] = state

	def get_button_state(self, device_iid, button_cid):
		state = self.button_states[device_iid][button_cid]
		while state == 'stale':
			self._refresh_button(device_iid, button_cid)
			time.sleep(0.1)
			state = self.button_states[device_iid][button_cid]
		return state

	def record_led_state(self, device_iid, led_cid, state):
		# should be called only by RaRepeater.repeaterReply()
		print "record_led_state: device %d led %d state %d" % (device_iid, led_cid, state)
		self.led_states[device_iid][led_cid] = state

	def get_led_state(self, device_iid, led_cid):
		state = self.led_states[device_iid][led_cid]
		while state == 'stale':
			self._refresh_led(device_iid, led_cid)
			time.sleep(0.1)
			state = self.led_states[device_iid][led_cid]
		return state

	def _refresh_output(self, iid):
		self.repeater.repeaterCommand('?OUTPUT,%d,1' % iid) # async

	def _refresh_button(self, iid, bid):
		# XXX docs don't show how to do this, or even that it can be done.
		# self.repeater.repeaterCommand('?DEVICE,%d,%d,X' % (iid, bid))
		# Responds "~ERROR,1" without the 3rd number, with "~ERROR,3" with
		# a X==0 or X>=2, and with "~DEVICE,iid,00000,1,1" for X==0 or X==1.
		# We find out that buttons are pressed/released when it actually
		# happens, so we can track state as it changes; let's just pretend
		# that all buttons are unpressed at startup.
		self.record_button_state(iid, bid, 0)

	def _refresh_led(self, iid, lid):
		self.repeater.repeaterCommand('?DEVICE,%d,%d,9' % (iid, lid)) # async

	def _bind_repeater(self, repeater):
		self.repeater = repeater
		for iid in self.output_levels.keys():
			self._refresh_output(iid)
		for iid in self.button_states.keys():
			for bid in self.button_states[iid].keys():
				self._refresh_button(iid, bid)
		for iid in self.led_states.keys():
			for lid in self.led_states[iid].keys():
				self._refresh_led(iid, lid)


class RaRepeater(object):
	state = None
	cache = None
	
	def __init__(self):
		self.verbose = False
		self._prep_response_handlers()
	
	def set_verbose(self, verbosity):
		self.verbose = verbosity
	
	def reset_cache(self, cache):
		self.cache = cache
		self.cache._bind_repeater(self)
	
	def get_output_level(self, output_iid):
		return self.cache.get_output_level(output_iid)

	def set_output_level(self, output_iid, level):
		self.repeaterCommand('#OUTPUT,%d,1,%g' % (output_iid, level))

	def get_button_state(self, device_iid, button_cid):
		return self.cache.get_button_state(device_iid, button_cid)

	def set_button_state(self, device_iid, button_cid, pressed):
		action = 3 if pressed else 4
		self.repeaterCommand('#DEVICE,%d,%d,%d' % (device_iid, button_cid, action))

	def get_led_state(self, device_iid, led_cid):
		return self.cache.get_led_state(device_iid, led_cid)

	def set_led_state(self, device_iid, led_cid, on):
		state = 1 if on else 0
		self.repeaterCommand('#DEVICE,%d,%d,9,%d' % (device_iid, led_cid, state))

	def connect(self, hostname, username, password):
		self.hostname = hostname
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.connect((hostname, 23))
		self.socket.setblocking(0)
		self.state = STATE_FRESH_CONNECTION
		self.startListenThread()

		self.waitForState(STATE_WANT_LOGIN)
		self.repeaterCommand(username)
		self.waitForState(STATE_WANT_PASSWORD)
		self.repeaterCommand(password)
		self.waitForState(STATE_READY)
		self.enable_monitoring()
		
	def enable_monitoring(self):
		self.repeaterCommand('#MONITORING,255,1')

	def repeaterCommand(self, cmd):
		self._setState(STATE_PROCESSING)
		if self.verbose:
			print 'debug: send %s' % repr(cmd)
		self.socket.send(cmd + CRLF)

	def _match_output_response(self, match):
		output = int(match.group(1))
		level = float(match.group(2))
		print "match %s -> output %d set level %g" % (match.group(), output, level)
		self.cache.record_output_level(output, level)

	def _match_button_response(self, match):
		device = int(match.group(1))
		component = int(match.group(2))
		action = int(match.group(3))
		print "match %s -> device %d button %d action %d" % (match.group(), device, component, action)
		state = True if action == 3 else False
		self.cache.record_button_state(device, component, state)

	def _match_led_response(self, match):
		device = int(match.group(1))
		component = int(match.group(2))
		parameter = int(match.group(3))
		print "match %s -> device %d led %d to %d" % (match.group(), device, component, parameter)
		# XXX doesn't handle LED flashing state
		state = True if parameter == 1 else False
		self.cache.record_led_state(device, component, state)

	def _prep_response_handlers(self):
		self.response_handler_list = [
			(re.compile('~OUTPUT,(\d+),1,(\d+.\d+)'), self._match_output_response),
			(re.compile('~DEVICE,(\d+),(\d+),9,(\d)'), self._match_led_response), # XXX: depend on order, since button regex will match led action too
			(re.compile('~DEVICE,(\d+),(\d+),(\d)'), self._match_button_response),
		]

	def repeaterReply(self, line):
		if self.verbose:
			print 'debug: reply %s' % repr(line)
		if line == 'GNET> ':
			self._setState(STATE_READY)
		elif line == 'login: ':
			self._setState(STATE_WANT_LOGIN)
		elif line == 'password: ':
			self._setState(STATE_WANT_PASSWORD)

		# TODO: more substantive processing of real commands
		# - should cache value for future gets (DONE)
		# - should handle output, led, and button (DONE)
		# - should announce this happened for historical logging
		for (pattern, handler) in self.response_handler_list:
			match = pattern.search(line) # XXX: should use match instead of search, but need to figure out the \rGNET issue
			if match:
				handler(match)
				break

	def startListenThread(self):
		class RepeaterListener(threading.Thread):
			repeater = None
			daemon = True

			def __init__(self, repeater):
				super(RepeaterListener, self).__init__()
				self.repeater = repeater

			def run(self):
				sock = self.repeater.socket
				verbose = self.repeater.verbose and False
				unprocessed = ''

				while True:
					# Run loop:
					# - block until socket is readable, then read whatever we can
					# - append new data to 'unprocessed'
					# - if 'unprocessed' contains any complete lines of input,
					#   send them over to main thread
					if verbose:
						print 'debug: listener thread block on input'
					(readable, writable, errored) = select.select([sock], [], [])
					if verbose:
						print 'debug: listener thread woke for input'
					assert readable == [sock]
					newInput = sock.recv(1024)
					# XXX: I don't know what embedded NUL bytes mean (e.g. after GNET prompt), but ignore them.
					newInput = newInput.replace('\x00', '')
					if verbose:
						print 'debug: listener thread read %d bytes: "%s"' % (len(newInput), repr(newInput))
					unprocessed += newInput
					lines = unprocessed.split(CRLF)
					if lines[-1] in ra_prompts:
						unprocessed = ''
					else:
						unprocessed = lines.pop()
					for line in lines:
						self.repeater.repeaterReply(line)

		self.stateEvent = threading.Event()
		self.listener = RepeaterListener(self)
		self.listener.start()
	
	def _setState(self, state):
		if self.verbose:
			print 'debug: state now %d' % state
		self.state = state
		# wake anyone waiting for this state change
		self.stateEvent.set()

	def waitForState(self, state):
		if self.verbose:
			print 'debug: want state %d' % state
		while self.state != state:
			self.stateEvent.clear()
			if self.state == state:
				print 'hahahaha!'
				break
			if self.verbose:
				print 'debug: wait for state change (now %d)' % self.state
			self.stateEvent.wait()
		if self.verbose:
			print 'debug: state wait satisfied'
