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
import Queue
import re
import socket
import time

import connections


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class OutputCache(object):
	# Low-level cache of last seen level for each device (output, button, led)

	# client public interface
	def __init__(self):
		self.repeater = None
		self.output_levels = {} # map from output iid to level
		self.button_states = {} # map from device iid to map from button component id to state
		self.led_states = {} # map from device iid to map from led component id to state
		self.refresh_count = dict() # map of iids for which we have a refresh in progress, to number of refreshes
		self.subscribers = [] # list of objects on which we will call on_user_action()

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
		self._broadcast_change(device_iid, state, button_cid)

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
		self.refresh_count[iid] = self.refresh_count.get(iid, 0) + 1;

	def _broadcast_change(self, iid, state, comp_id = 0):
		if iid in self.refresh_count:
			# if we had a refresh in progress, don't send an update, but decrement
			# the count of refreshes in progress
			refresh = True
			self.refresh_count[iid] = self.refresh_count[iid] - 1;
			if self.refresh_count[iid] == 0:
				del self.refresh_count[iid]
				logger.debug('broadcast_change: removed ignore flag for iid %d' % iid)
		else: # the normal case, where a refresh is not in progress
			refresh = False
		logger.debug('broadcast_change: sending on_user_action(iid=%d, refresh=%s)' % (iid, str(refresh)))
		for subscriber in self.subscribers:
			subscriber.on_user_action(iid, state, refresh, comp_id)


class RaRepeater(object):
	def __init__(self, watchdog):
		self.watchdog = watchdog
		self.state = None
		self.cache = None
		self._prep_response_handlers()
	
	def bind_cache(self, cache):
		self.cache = cache
		self.cache._bind_repeater(self)
	
	def connect(self, hostname, username, password):
		self.hostname = hostname
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.connect((hostname, 23))

		# authenticate to repeater using simple blocking calls
		buf = self.socket.recv(1024)
		assert(buf == 'login: ')
		self.socket.send(username + '\r\n')
		buf = self.socket.recv(1024)
		assert(buf == 'password: ')
		self.socket.send(password + '\r\n')
		buf = self.socket.recv(1024)
		# good response: \r\nGNET> \x00; bad response: bad login\r\nlogin: \x00
		assert(buf.startswith('\r\nGNET> '))

		# then put socket in nonblocking mode and start reader/writer threads
		self.socket.setblocking(0)
		self.listen_thread = connections.ListenerThread(self, 'ra')
		self.listen_thread.start()
		self.send_queue = Queue.Queue()
		self.send_thread = connections.SenderThread(self, 'ra')
		self.send_thread.start()

		# enable automatic reconnect
		self.watchdog.add([self.listen_thread, self.send_thread], self.socket,
			lambda: self.connect(hostname, username, password))

		# finally kick off by requesting further updates
		self.enable_monitoring()
		
	def get_output_level(self, output_iid):
		return self.cache.get_output_level(output_iid)

	def set_output_level(self, output_iid, level):
		self.send_repeater_command('#OUTPUT,%d,1,%g' % (output_iid, level))

	def pulse_output(self, output_iid):
		self.send_repeater_command('#OUTPUT,%d,6' % (output_iid))

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

	def _match_monitoring_response(self, match):
		# we catch this just to avoid complaint about unhandled command; we don't need to do anything
		logger.debug('match %s -> monitoring mode now %s,%s' % (match.group(), match.group(1), match.group(2)))

	def _prep_response_handlers(self):
		self.prompt_re = re.compile('^\s*(GNET> )+(.*)$')
		self.response_handler_list = [
			(re.compile('~OUTPUT,(\d+),1,(\d+.\d+)'), self._match_output_response),
			(re.compile('~DEVICE,(\d+),(\d+),9,(\d)'), self._match_led_response), # XXX: depend on order, since button regex will match led action too
			(re.compile('~DEVICE,(\d+),(\d+),(\d)'), self._match_button_response),
			(re.compile('~MONITORING,(\d+),(\d+)'), self._match_monitoring_response),
		]

	def enable_monitoring(self):
		self.send_repeater_command('#MONITORING,255,1')

	def send_repeater_command(self, cmd):
		logger.debug('send_repeater_command: enqueue %s' % repr(cmd))
		self.send_queue.put(str(cmd))

	def receive_from_listener(self, cmd):
		self.receive_repeater_reply(cmd)

	def receive_repeater_reply(self, line):
		logger.debug('receive_repeater_reply: reply %s' % repr(line))
		# Prompts can occur on a line by themself, or as the prefix of a line containing additional
		# data. So we look for the prompt as a prefix, if found strip it off, then continue handling
		# the rest of the line.
		match = self.prompt_re.match(line)
		if match:
			line = match.group(2)

		if len(line) > 0:
			# Try to parse remainder as monitoring response
			for (pattern, handler) in self.response_handler_list:
				match = pattern.match(line)
				if match:
					handler(match)
					break
			if not match:
				logger.warning('unmatched repeater reply: %s' % repr(line))
