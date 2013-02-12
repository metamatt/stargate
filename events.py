# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides the message bus for event notifications.

import logging


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class SgEvents(object):
	def __init__(self, persist):
		# XXX this should have a subscriber list and forward that way, without hardcoded
		# references to self.persist
		self.persist = persist
		self.subscribers = {}


	def subscribe(self, device, handler):
		if not self.subscribers.has_key(device):
			self.subscribers[device] = []
		handlers = self.subscribers[device]
		handlers.append(handler)

	def notify_subscribers(self, device, synthetic):
		if self.subscribers.has_key(device):
			handlers = self.subscribers[device]
			for handler in handlers:
				handler(synthetic)

	# XXX: may want to pull init_device_state back out of events, and have devices register with that
	# into persist and get back a sg_devid which they then use here and as the public interface to the
	# rest of persist?
	def on_device_state_change(self, device, synthetic = False):
		gateway_id = device.gateway.gateway_id
		gateway_device_id = device.gateway_devid
		level = device.get_level()

		# call registered handlers interested in this specific device
		self.notify_subscribers(device, synthetic)

		# forward all events to persist
		if synthetic:
			logger.info('device %s:%s reports state currently %s (synthetic, no change)' % (gateway_id, gateway_device_id, level))
			self.persist.record_startup(gateway_id, gateway_device_id, level)
		else:
			logger.info('device %s:%s reports state change to %s' % (gateway_id, gateway_device_id, level))
			self.persist.record_change(gateway_id, gateway_device_id, level)
