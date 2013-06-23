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
		# XXX persist should subscribe via the normal subscriber list, instead of
		# us having this hardcoded dependency here
		self.persist = persist
		self.subscribers = {}


	def subscribe(self, device, handler):
		if not self.subscribers.has_key(device):
			self.subscribers[device] = []
		handlers = self.subscribers[device]
		handlers.append(handler)
		logger.info('device %s now has %d handlers' % (device.get_internal_name(), len(handlers)))

	def notify_subscribers(self, device, synthetic):
		if self.subscribers.has_key(device):
			handlers = self.subscribers[device]
			logger.info('device %s invoking %d handlers' % (device.get_internal_name(), len(handlers)))
			for handler in handlers:
				handler(synthetic)

	# XXX: may want to pull init_device_state back out of events, and have devices register with that
	# into persist and get back a sg_devid which they then use here and as the public interface to the
	# rest of persist?
	def on_device_state_change(self, device, synthetic = False):
		dev_debug_id = device.get_internal_name()
		device_id = device.device_id
		level = device.get_level()

		suffix = synthetic and ' (synthetic, no change)' or ''
		logger.info('device %s reports state currently %s%s' % (dev_debug_id, level, suffix))

		# call registered handlers interested in this specific device
		self.notify_subscribers(device, synthetic)

		# forward all events to persist
		self.persist.record_startup(device_id, level)
