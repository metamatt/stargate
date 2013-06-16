# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Cross-device control for Stargate.
#
# This module provides Stargate devoce objects which bind and delegate
# to existing devices exposed by other gateways.
#

import logging
import time

from sg_util import AttrDict
import sg_house


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class Bridge(object):
	def __init__(self, synthesizer, params):
		logger.info('create bridge for %s' % str(params))
		self.synth = synthesizer
		house = synthesizer.house

		# Locate devices to operate on
		# XXX for now, behavior is hardcoded to handle radiora2<>powerseries the way I'm using them
		ra_dev = house.get_device_by_gateway_and_id('radiora2', params['radiora2'])
		dsc_zone = house.get_device_by_gateway_and_id('powerseries', 'zone:%d' % params['dsc_zone'])
		(dsc_partition, dsc_cmd_id) = map(int, str(params['dsc_cmd'])) # split out the digits

		# Suck initial state from DSC and push into Lutron
		logger.debug('Currently: Lutron says %s; DSC says %s' % (ra_dev.is_on(), dsc_zone.is_open()))
		ra_dev.be_on(dsc_zone.is_open())

		# Watch when Lutron says to change it (Lutron button/remote/integration)
		def on_lutron_push(synthetic):
			logger.debug('lutron dev %d changed to %s %s' % (ra_dev.iid, ra_dev.is_on(), ' synthetic' if synthetic else ''))
			if ra_dev.is_on() != dsc_zone.is_open():
				logger.debug('telling dsc to toggle p%dd%d' % (dsc_partition, dsc_cmd_id))
				dsc_zone.gateway.send_user_command(dsc_partition, dsc_cmd_id)
			else:
				logger.debug('ignoring lutron dev-change for %d to already-current state %s' % (ra_dev.iid, ra_dev.is_on()))
		house.events.subscribe(ra_dev, on_lutron_push)

		# Watch when DSC says it did change (someone used an old-school switch)
		def on_physical_push(synthetic):
			logger.debug('synther.bridge: dsc dev %d changed to %s' % (dsc_zone.zone_number, dsc_zone.is_open()))
			ra_dev.be_on(dsc_zone.is_open())
		house.events.subscribe(dsc_zone, on_physical_push)


class LedBridge(object):
	def __init__(self, synthesizer, params):
		logger.info('create ledbridge for %s' % str(params))
		self.synth = synthesizer
		house = synthesizer.house

		# Locate devices to operate on
		# XXX for now, behavior is hardcoded to handle powerseries zone -> radiora2 keypad button led
		ra_keypad = house.get_device_by_gateway_and_id('radiora2', params['radiora2_keypad'])
		ra_button = ra_keypad.get_button(params['radiora2_button_cid'])
		dsc_zone = house.get_device_by_gateway_and_id('powerseries', 'zone:%d' % params['dsc_zone'])
		negate = params['negate']
		if negate:
			map_state = lambda state: not state
		else:
			map_state = lambda state: state

		# Watch when DSC says it changed
		def on_change(synthetic):
			logger.debug('synther.ledbridge: dsc dev %d changed to %s' % (dsc_zone.zone_number, dsc_zone.is_open()))
			ra_button.set_led_state(map_state(dsc_zone.is_open()))
		house.events.subscribe(dsc_zone, on_change)
		# Call once now to suck initial state from DSC and push into Lutron
		on_change(True)


class Delay(object):
	def __init__(self, synthesizer, params):
		logger.info('create delay-reaction for %s' % str(params))
		self.synth = synthesizer
		house = synthesizer.house

		# Locate device to operate on
		# XXX for now, behavior is hardcoded to handle radiora2 keypad -> radiora2 device
		ra_keypad = house.get_device_by_gateway_and_id('radiora2', params['radiora2_keypad'])
		ra_button = ra_keypad.get_button(params['radiora2_button_cid'])
		ra_output = house.get_device_by_gateway_and_id('radiora2', params['radiora2_output'])
		delay = params['delay']
		value = params['value']

		# Watch when Lutron says button state changed
		class NonlocalState(object): # to supply writable state in nonlocal scope for nested functions to follow
			def __init__(self, pressed):
				self.pressed = pressed
				self.timer_token = None
		state = NonlocalState(ra_button.get_button_state())
		def on_delay():
			logger.debug('synther.delay: delay elapsed; set dev %d to %s' % (ra_keypad.iid, value))
			if value == 'pulse':
				ra_output.pulse_output()
			else:
				ra_output.set_level(int(value))
			state.timer_token = None
		def on_lutron_push(synthetic):
			# Button state changed; response depends on old and new states
			pressed = ra_button.get_button_state()
			# If newly pressed: install timer callback
			if pressed and not state.pressed:
				if state.timer_token is None:
					state.timer_token = house.timer.add_event(delay, on_delay)
			# If released with timer callback pending: cancel timer callback
			if state.pressed and not pressed:
				if state.timer_token is not None:
					house.timer.cancel_event(state.timer_token)
					state.timer_token = None
			state.pressed = pressed
			# If timer callback elapses while still pressed: take action
		house.events.subscribe(ra_keypad, on_lutron_push)


class Paranoid(object):
	def __init__(self, synthesizer, params):
		logger.info('create paranoid for %s' % str(params))
		self.synth = synthesizer
		house = synthesizer.house

		# Locate devices to operate on
		gateway = params['gateway']
		dev_to_watch = house.get_device_by_gateway_and_id(gateway, params['device'])
		delay = params['delay']
		notify_alias = params['notify']
		bad_state = params['state']
		watched_dev_in_bad_state = getattr(dev_to_watch, 'is_' + bad_state)
		# Check up front and fail early if someone configures paranoid without configuring notifications.
		assert house.notify.can_notify(notify_alias)

		# Helpers for following on_change handler
		class NonlocalState(object): # to supply writable state in nonlocal scope for nested functions to follow
			def __init__(self):
				self.timer_token = None
				self.bad_since = None
				self.warned_at = None
		state = NonlocalState()
		def send_notification(state_is_bad):
			if state_is_bad:
				delay_descr = '%d seconds' % delay # XXX should convert this to friendly time
				msg = (('Watched device "%s" has been "%s" for %s.\n\n' +
					'Stargate will send confirmation when this problem is fixed; ' +
					'it will not send further warnings while it stays %s.')
				       % (dev_to_watch.name, bad_state, delay_descr, bad_state))
				# XXX add "Entered bad 'open' state at <bad_since> (x units ago)"
				# XXX add "Warning generated at <warned_at>"
				subject = 'Stargate: %s %s warning' % (dev_to_watch.name, bad_state)
			else:
				msg = (('Watched device "%s" is no longer "%s".\n\n' +
				       'You can stop worrying.')
				      % (dev_to_watch.name, bad_state))
				# XXX add "Entered bad 'open' state at <bad_since> (x units ago)"
				# XXX add "Sent warning bad 'open' state at <warned_at> (x units ago)"
				# XXX add "Left bad 'open' state at <timestamp>"
				subject = 'Stargate: %s %s fixed' % (dev_to_watch.name, bad_state)
			house.notify.notify(notify_alias, msg, subject)
		def on_delay():
			logger.debug('synther.paranoid: delay elapsed; notify group alias ' + notify_alias)
			state.warned_at = time.time()
			send_notification(True)

		# Watch when gateway says it changed
		def on_change(synthetic):
			logger.debug('synther.paranoid: dev %s:%s changed to %s' % (gateway, dev_to_watch.name, watched_dev_in_bad_state()))
			if watched_dev_in_bad_state():
				if state.timer_token is None:
					state.bad_since = time.time()
					state.timer_token = house.timer.add_event(delay, on_delay)
			else:
				# Device in good state. Remove any pending alarm, and if we already triggered
				# the alarm and sent a badness notification, follow it with a goodness notification.
				if state.timer_token is not None:
					house.timer.cancel_event(state.timer_token)
					state.timer_token = None
				if state.warned_at is not None:
					logger.debug('synther.paranoid: violation corrected; notify group alias ' + notify_alias)
					send_notification(False)
				state.bad_since = None
				state.warned_at = None
		house.events.subscribe(dev_to_watch, on_change)
		# Call once now so if it's open, we start counting
		on_change(True)


class Synthesizer(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, bridges, ledbridges, delays, paranoids):
		super(Synthesizer, self).__init__(house, gateway_instance_name)
		self.bridges = []
		for bridge in bridges:
			self.bridges.append(Bridge(self, bridge))

		self.ledbridges = []
		for ledbridge in ledbridges:
			self.ledbridges.append(LedBridge(self, ledbridge))

		self.delays = []
		for delay in delays:
			self.delays.append(Delay(self, delay))

		self.paranoids = []
		for paranoid in paranoids:
			self.paranoids.append(Paranoid(self, paranoid))

	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		# XXX this is uncalled since we don't create StargateDevices
		assert False
