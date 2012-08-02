# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system.
#
# This module handles the TCP connection to the repeater,
# and listens to it in monitor mode to build a cache of
# device state for the entire system. It provides a low-level
# interface for querying and changing the state of outputs
# and devices.

import logging
import re
import select
import socket
import time
import threading


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

# states we recognize in repeater listener
STATE_FRESH_CONNECTION, STATE_PROCESSING, STATE_WANT_LOGIN, STATE_WANT_PASSWORD, STATE_READY = range(5)
# Map of repeater prompts to the states they indicate. We define "prompt" as the repeater responses
# that mean the repeater wants to hear from us next, and won't be followed by CRLF.
ra_prompt_map = {
	'login: ': STATE_WANT_LOGIN,
	'password: ': STATE_WANT_PASSWORD,
	'GNET> \x00': STATE_READY, # XXX I don't know why, but the first GNET response after login always has a NUL byte there
	'\rGNET> ': STATE_READY, # XXX note that the first GNET response is preceded by \r\n which we split on the line separator
	# so we don't treat it as part of the response, but all further GNET responses have only \r which we don't split out
	# and thus do see.
}
CRLF = '\r\n'


class OutputCache(object):
	# Low-level cache of last seen level for each device (output, button, led)
	repeater = None
	output_levels = {} # map from output iid to level
	button_states = {} # map from device iid to map from button component id to state
	led_states = {} # map from device iid to map from led component id to state
	refreshing = set() # set of iids for which we have a refresh in progress
	subscribers = [] # list of objects on which we will call on_user_action()

	# client public interface
	def __init__(self):
		pass

	def watch_output(self, output_iid):
		self.output_levels[output_iid] = 'stale'
	
	def watch_device(self, device_iid, button_cids, led_cids):
		button = self.button_states[device_iid] = dict()
		for cid in button_cids:
			button[cid] = 'stale'
		led = self.led_states[device_iid] = dict()
		for cid in led_cids:
			led[cid] = 'stale'

	def subscribe_to_actions(self, subscriber):
		assert hasattr(subscriber, 'on_user_action')
		self.subscribers.append(subscriber)

	def get_output_level(self, output_iid):
		level = self.output_levels[output_iid]
		while level == 'stale':
			self._refresh_output(output_iid)
			time.sleep(0.1)
			level = self.output_levels[output_iid]
		return level

	def get_button_state(self, device_iid, button_cid):
		state = self.button_states[device_iid][button_cid]
		while state == 'stale':
			self._refresh_button(device_iid, button_cid)
			time.sleep(0.1)
			state = self.button_states[device_iid][button_cid]
		return state

	def get_led_state(self, device_iid, led_cid):
		state = self.led_states[device_iid][led_cid]
		while state == 'stale':
			self._refresh_led(device_iid, led_cid)
			time.sleep(0.1)
			state = self.led_states[device_iid][led_cid]
		return state

	# RaRepeater private interface
	def _record_output_level(self, output_iid, level):
		# should be called only by RaRepeater.receive_repeater_reply()
		logger.info('record_output_level: output %d level %d' % (output_iid, level))
		self.output_levels[output_iid] = level
		self._broadcast_change(output_iid, level)

	def _record_button_state(self, device_iid, button_cid, state):
		# should be called only by RaRepeater.receive_repeater_reply()
		logger.info('record_button_state: device %d button %d state %d' % (device_iid, button_cid, state))
		self.button_states[device_iid][button_cid] = state
		self._broadcast_change(device_iid, state)

	def _record_led_state(self, device_iid, led_cid, state):
		# should be called only by RaRepeater.receive_repeater_reply()
		logger.info('record_led_state: device %d led %d state %d' % (device_iid, led_cid, state))
		self.led_states[device_iid][led_cid] = state
		# XXX for now at least, we don't send state change notifications for LEDs

	def _bind_repeater(self, repeater):
		self.repeater = repeater
		# now that we have a repeater, do an async/background refresh of all cacheable state
		for iid in self.output_levels.keys():
			self._refresh_output(iid)
		for iid in self.button_states.keys():
			for bid in self.button_states[iid].keys():
				self._refresh_button(iid, bid)
		for iid in self.led_states.keys():
			for lid in self.led_states[iid].keys():
				self._refresh_led(iid, lid)

	# internal private interface
	def _refresh_output(self, iid):
		self._mark_refresh_pending(iid)
		self.repeater.send_repeater_command('?OUTPUT,%d,1' % iid) # async

	def _refresh_button(self, iid, bid):
		self._mark_refresh_pending(iid)
		# XXX docs don't show how to do this, or even that it can be done.
		# self.repeater.send_repeater_command('?DEVICE,%d,%d,X' % (iid, bid))
		# Responds "~ERROR,1" without the 3rd number, with "~ERROR,3" with
		# a X==0 or X>=2, and with "~DEVICE,iid,00000,1,1" for X==0 or X==1.
		# We find out that buttons are pressed/released when it actually
		# happens, so we can track state as it changes; let's just pretend
		# that all buttons are unpressed at startup.
		self._record_button_state(iid, bid, 0)

	def _refresh_led(self, iid, lid):
		self._mark_refresh_pending(iid)
		self.repeater.send_repeater_command('?DEVICE,%d,%d,9' % (iid, lid)) # async

	def _mark_refresh_pending(self, iid):
		# Record that we're asking the repeater for status, so when a status message
		# arrives, it came from us and not a user action -- so don't broadcast an
		# on_update message
		logger.debug('mark_for_refresh: setting ignore flag for iid %d' % iid)
		self.refreshing.add(iid)
		
	def _broadcast_change(self, iid, state):
		# XXX do details matter? (for device, which button, which state? even if not button, should we avoid separate press+release msgs?)
		try: # if we had a refresh in progress, unmark it and don't send an update
			self.refreshing.remove(iid)
			logger.debug('broadcast_change: removed ignore flag for iid %d' % iid)
			refresh = True
		except KeyError: # the normal case, where a refresh is not in progress
			refresh = False
		logger.debug('broadcast_change: sending on_user_action(iid=%d, refresh=%s)' % (iid, str(refresh)))
		for subscriber in self.subscribers:
			subscriber.on_user_action(iid, state, refresh)


class RaRepeater(object):
	state = None
	cache = None
	
	def __init__(self):
		self._prep_response_handlers()
	
	def bind_cache(self, cache):
		self.cache = cache
		self.cache._bind_repeater(self)
	
	def get_output_level(self, output_iid):
		return self.cache.get_output_level(output_iid)

	def set_output_level(self, output_iid, level):
		self.send_repeater_command('#OUTPUT,%d,1,%g' % (output_iid, level))

	def get_button_state(self, device_iid, button_cid):
		return self.cache.get_button_state(device_iid, button_cid)

	def set_button_state(self, device_iid, button_cid, pressed):
		action = 3 if pressed else 4
		self.send_repeater_command('#DEVICE,%d,%d,%d' % (device_iid, button_cid, action))

	def get_led_state(self, device_iid, led_cid):
		return self.cache.get_led_state(device_iid, led_cid)

	def set_led_state(self, device_iid, led_cid, on):
		state = 1 if on else 0
		self.send_repeater_command('#DEVICE,%d,%d,9,%d' % (device_iid, led_cid, state))

	def connect(self, hostname, username, password):
		self.hostname = hostname
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.connect((hostname, 23))
		self.socket.setblocking(0)
		self.state = STATE_FRESH_CONNECTION
		self.start_listen_thread()

		self.wait_for_state(STATE_WANT_LOGIN)
		self.send_repeater_command(username)
		self.wait_for_state(STATE_WANT_PASSWORD)
		self.send_repeater_command(password)
		self.wait_for_state(STATE_READY)
		self.enable_monitoring()
		
	def enable_monitoring(self):
		self.send_repeater_command('#MONITORING,255,1')

	def send_repeater_command(self, cmd):
		self._set_repeater_state(STATE_PROCESSING)
		logger.debug('send_repeater_command: send %s' % repr(cmd))
		sent = self.socket.send(cmd + CRLF)
		if sent != len(cmd) + 2:
			logger.warning('send_repeater_command: sent %d of %d bytes' % (sent, 2 + len(cmd)))

	def _match_output_response(self, match):
		output = int(match.group(1))
		level = float(match.group(2))
		logger.debug('match %s -> output %d set level %g' % (match.group(), output, level))
		self.cache._record_output_level(output, level)

	def _match_button_response(self, match):
		device = int(match.group(1))
		component = int(match.group(2))
		action = int(match.group(3))
		logger.debug('match %s -> device %d button %d action %d' % (match.group(), device, component, action))
		state = True if action == 3 else False
		self.cache._record_button_state(device, component, state)

	def _match_led_response(self, match):
		device = int(match.group(1))
		component = int(match.group(2))
		parameter = int(match.group(3))
		logger.debug('match %s -> device %d led %d to %d' % (match.group(), device, component, parameter))
		# XXX doesn't handle LED flashing state
		state = True if parameter == 1 else False
		self.cache._record_led_state(device, component, state)

	def _prep_response_handlers(self):
		self.response_handler_list = [
			(re.compile('~OUTPUT,(\d+),1,(\d+.\d+)'), self._match_output_response),
			(re.compile('~DEVICE,(\d+),(\d+),9,(\d)'), self._match_led_response), # XXX: depend on order, since button regex will match led action too
			(re.compile('~DEVICE,(\d+),(\d+),(\d)'), self._match_button_response),
		]

	def receive_repeater_reply(self, line):
		logger.debug('receive_repeater_reply: reply %s' % repr(line))
		# Handle prompts as state transitions. These can occur on a line by themself, or as the
		# prefix of a line containing additional data. So we look for the prompt as a prefix,
		# if found act on it and strip it off, then continue handling the rest of hte line.
		for prompt in ra_prompt_map:
			if line.startswith(prompt):
				self._set_repeater_state(ra_prompt_map[prompt])
				line = line[len(prompt):]

		if len(line) > 0:
			# Try to parse remainder as monitoring response
			# TODO: more substantive processing of real commands
			# - should cache value for future gets (DONE)
			# - should handle output, led, and button (DONE)
			# - should announce this happened for historical logging
			for (pattern, handler) in self.response_handler_list:
				match = pattern.match(line)
				if match:
					handler(match)
					break
			if not match:
				logger.warning('unmatched repeater reply: %s' % repr(line))

	def start_listen_thread(self):
		# Set up our own logger (note that it is used by scope, not by thread! The code lexically inside
		# this function will use it; if we call other functions, they will not... ok?)
		logger = logging.getLogger(__name__ + '.listener')
		logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))
		class RepeaterListener(threading.Thread):
			repeater = None
			daemon = True

			def __init__(self, repeater):
				super(RepeaterListener, self).__init__(name = 'ra_repeater')
				self.repeater = repeater

			def run(self):
				sock = self.repeater.socket
				unprocessed = ''

				try:
					while True:
						# Run loop:
						# - block until socket is readable, then read whatever we can
						# - append new data to 'unprocessed'
						# - if 'unprocessed' contains any complete lines of input,
						#   send them over to main thread
						logger.debug('debug: listener thread block on input')
						(readable, writable, errored) = select.select([sock], [], [sock])
						logger.debug('debug: listener thread woke for input with %d/%d/%d sockets r/w/e' % (len(readable), len(writable), len(errored)))
						assert readable == [sock]
						newInput = sock.recv(1024)
						logger.debug('debug: listener thread read %d bytes: %s' % (len(newInput), repr(newInput)))
						if len(newInput) == 0:
							raise Exception('repeater closed socket')
						# Now combine and parse pending data (new and old-unprocessed). Append new data,
						# split into lines, and if the last line is not a known prompt, stick it back in
						# the pending pile. (We expect all replies to eventually go back to the GNET
						# prompt, so if we read a response that doesn't end with a prompt, we don't know
						# whether it's complete, and we do know more data is coming, so we wait for more
						# before deciding how to parse this.)
						unprocessed += newInput
						lines = unprocessed.split(CRLF)
						unprocessed = ''
						if lines[-1] not in ra_prompt_map:
							unprocessed = lines.pop()
						# Now send complete received lines of data back to main thread for processing.
						for line in lines:
							self.repeater.receive_repeater_reply(line)
				except:
					logger.exception('repeater listener died')
					# XXX should reconnect...

		self.stateEvent = threading.Event()
		self.listener = RepeaterListener(self)
		self.listener.start()
	
	def _set_repeater_state(self, state):
		logger.debug('debug: state now %d' % state)
		self.state = state
		# wake anyone waiting for this state change
		self.stateEvent.set()

	def wait_for_state(self, state):
		logger.debug('debug: want state %d' % state)
		while self.state != state:
			self.stateEvent.clear()
			if self.state == state:
				logger.debug('debug: found requested state')
				break
			logger.debug('debug: wait for state change (now %d)' % self.state)
			self.stateEvent.wait()
		logger.debug('debug: state wait satisfied')
