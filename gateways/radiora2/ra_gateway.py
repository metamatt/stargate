# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system.
#
# This module provides high-level objects representing the various
# RadioRa2 devices.

import logging

import sg_house
import ra_layout
import ra_repeater


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

class LutronDevice(sg_house.StargateDevice):
	# Individual RadioRa device -- includes both controllable outputs (what Lutron calls an "output")
	# and we will subclass as "OutputDevice") and inputs/controls (what Lutron calls an "input", I
	# would typically call a "keypad", and we will subclass as "ControlDevice").

	@staticmethod
	def order_states(states):
		return [state for state in (OutputDevice.KNOWN_STATES_IN_ORDER[:-1] + ControlDevice.KNOWN_STATES_IN_ORDER) if state in states]

	iid = None
	devclass = None
	devtype = None
	
	def __init__(self, devclass, ra_area, iid, name):
		super(LutronDevice, self).__init__(ra_area.house, ra_area.sg_area, ra_area.gateway, str(iid), name)
		self.devclass = devclass
		self.ra_area = ra_area
		self.iid = iid
		self.gateway._register_device(self)


class OutputDevice(LutronDevice):
	# Common device subclass for controllable outputs (lights, shades, appliances).

	KNOWN_STATES_IN_ORDER = [ 'light', 'closed', 'off', 'half', 'on', 'shade', 'open', 'contactclosure', 'all' ]
	@staticmethod
	def order_states(states):
		return [state for state in OutputDevice.KNOWN_STATES_IN_ORDER if state in states]

	def __init__(self, ra_area, device_spec):
		super(OutputDevice, self).__init__('output', ra_area, device_spec.iid, device_spec.name)
		self.level_step = 100

	# interface to get/set output levels (device scope)
	def get_level(self):
		return self.gateway._get_output_level(self.iid)

	def set_level(self, level):
		self.gateway._set_output_level(self.iid, level)

	def go_to_state(self, state):
		handler = 'be_' + state
		if not hasattr(self, handler):
			return False
		getattr(self, handler)()
		return True

	def get_name_for_level(self, level):
		return 'on' if level > 0 else 'off'

	def on_user_action(self, level, refresh):
		assert level == self.get_level()
		self.gateway._on_device_state_change(self.iid, level > 0, refresh)
	

class SwitchedOutput(OutputDevice):
	def __init__(self, ra_area, device_spec):
		super(SwitchedOutput, self).__init__(ra_area, device_spec)
		self.devtype = 'light'

	def is_on(self):
		return self.get_level() > 0

	def be_on(self):
		self.set_level(100)

	def is_off(self):
		return self.get_level() == 0
		
	def be_off(self):
		self.set_level(0)


class DimmedOutput(SwitchedOutput):
	def __init__(self, ra_area, device_spec):
		super(DimmedOutput, self).__init__(ra_area, device_spec)
		self.level_step = 1

	def be_half(self):
		self.set_level(50)


class ShadeOutput(OutputDevice):
	def __init__(self, ra_area, device_spec):
		super(ShadeOutput, self).__init__(ra_area, device_spec)
		self.devtype = 'shade'
		self.level_step = 1
	
	def be_half(self):
		self.set_level(50)

	def is_closed(self):
		return self.get_level() <= 0.5 # some slop
	
	def be_closed(self):
		self.set_level(0)

	def is_open(self):
		return not self.is_closed()

	def is_fully_open(self):
		return self.get_level() >= 99.5 # I've seen 99.61, 100.01... allow some slop

	def be_open(self):
		self.set_level(100)

	def get_name_for_level(self, level):
		return 'open' if level > 0 else 'closed'


class ContactClosureOutput(OutputDevice):
	def __init__(self, ra_area, device_spec):
		super(ContactClosureOutput, self).__init__(ra_area, device_spec)
		self.pulsed = device_spec.get_type() == 'CCO_PULSED'
		self.devtype = 'contactclosure'

	# XXX does it make more sense to people to define the states for CCOs as
	# open/closed or on/off?
	def is_closed(self):
		return self.get_level() == 0

	def be_closed(self):
		self.set_level(0)

	def is_open(self):
		return self.get_level() > 0

	def be_open(self):
		self.set_level(100)

	def get_name_for_level(self, level):
		return 'active' if level > 0 else 'inactive'


class ControlDevice(LutronDevice):
	# Common device subclass for controls (keypads, remotes, repeater/receiver buttons).

	KNOWN_STATES_IN_ORDER = [ 'keypad', 'remote', 'repeater', 'all' ]
	@staticmethod
	def order_states(states):
		return [state for state in ControlDevice.KNOWN_STATES_IN_ORDER if state in states]

	def __init__(self, ra_area, device_spec):
		super(ControlDevice, self).__init__('control', ra_area, device_spec.iid, device_spec.name)


class KeypadButton(object):
	def __init__(self, device, button_cid, label, led_cid):
		self.device = device
		self.button_cid = button_cid
		self.label = label
		self.led_cid = led_cid

	def has_led(self):
		return self.led_cid is not None

	def get_button_state(self):
		return self.device.gateway._get_button_state(self.device.iid, self.button_cid)

	def get_led_state(self):
		return self.device.gateway._get_led_state(self.device.iid, self.led_cid)
		
	def set_button_state(self, pressed):
		self.device.gateway._set_button_state(self.device.iid, self.button_cid, pressed)
		
	def set_led_state(self, on):
		self.device.gateway._set_led_state(self.device.iid, self.led_cid, on)


class KeypadDevice(ControlDevice):
	def __init__(self, ra_area, device_spec):
		super(KeypadDevice, self).__init__(ra_area, device_spec)
		self.devtype = 'keypad'
		self.buttons = dict()
		for button_id in device_spec.buttons.keys():
			led_cid = button_id + 80 # it just works out that way
			if not led_cid in device_spec.leds:
				led_cid = None
			self._add_button(button_id, device_spec.buttons[button_id], led_cid)

	def _add_button(self, cid, label, has_led):
		self.buttons[cid] = KeypadButton(self, cid, label, has_led)
	
	def get_button_ids(self):
		return sorted(self.buttons.keys())
	
	def get_button(self, button_cid):
		return self.buttons[button_cid]

	def get_any_button_pressed(self):
		return any([b.get_button_state() for b in self.buttons.values()])

	def get_num_buttons_pressed(self):
		if not len(self.buttons):
			return 0
		return reduce(lambda x, y: x+y, [(1 if b.get_button_state() else 0) for b in self.buttons.values()])
		
	def get_level(self):
		return self.get_num_buttons_pressed()

	def on_user_action(self, state, refresh):
		self.gateway._on_device_state_change(self.iid, state, refresh)

	def get_name_for_level(self, level):
		return 'pressed' if level > 0 else 'unpressed'


class RemoteKeypadDevice(KeypadDevice):
	def __init__(self, ra_area, device_spec):
		super(RemoteKeypadDevice, self).__init__(ra_area, device_spec)
		self.devtype = 'remote'


class RepeaterKeypadDevice(KeypadDevice):
	def __init__(self, ra_area, device_spec):
		super(RepeaterKeypadDevice, self).__init__(ra_area, device_spec)
		self.devtype = 'repeater'


def create_device_for_output(ra_area, output_spec):
	# Static factory for correct OutputDevice subclass matching Lutron OutputType.
	map_lutron_output_to_class = {
		"INC": DimmedOutput,
		"NON_DIM": SwitchedOutput,
		"SYSTEM_SHADE": ShadeOutput,
		"CCO_PULSED": ContactClosureOutput,
		"CCO_MAINTAINED": ContactClosureOutput,
	}
	
	try:
		cls = map_lutron_output_to_class[output_spec.get_type()]
	except: # XXX fall back on default/generic case
		logger.error('unknown lutron device type: %s' % device_spec.get_type())
		cls = OutputDevice

	return cls(ra_area, output_spec)


def create_device_for_control(ra_area, device_spec):
	# Static factory for correct ControlDevice subclass matching Lutron DeviceType.
	map_lutron_device_to_class = {
		"SEETOUCH_KEYPAD": KeypadDevice,
		"SEETOUCH_TABLETOP_KEYPAD": KeypadDevice,
		"HYBRID_SEETOUCH_KEYPAD": KeypadDevice,
		"PICO_KEYPAD": RemoteKeypadDevice,
		"VISOR_CONTROL_RECEIVER": RepeaterKeypadDevice,
		"MAIN_REPEATER": RepeaterKeypadDevice,
	}

	try:
		cls = map_lutron_device_to_class[device_spec.get_type()]
	except: # XXX fall back on default/generic case
		logger.error('unknown lutron device type: %s' % device_spec.get_type())
		cls = ControlDevice

	return cls(ra_area, device_spec)


class RaArea(object):
	# grouping container: area containing a set of devices and/or other areas
	# (Matches Lutron's "area" concept).
	
	# XXX should clean up constructor arguments, deal with nested areas, and avoid
	# needing to pass the house to nested areas. This should just take a "parent"
	# argument.
	# XXX that comment predates the conversion to StargateArea; not sure whether
	# it's now more or less necessary to do the above, but it bears rethinking.
	# XXX this whole class is almost vestigial now; all it does is create the right
	# hierarchy of StargateHouse objects.
	def __init__(self, gateway, area_spec):
		self.gateway = gateway
		self.house = gateway.house

		self.iid = area_spec.iid
		self.name = area_spec.name
		self.sg_area = gateway._register_area(self)
		self.members = [create_device_for_output(self, output_spec) for output_spec in area_spec.get_outputs()] + [
					    create_device_for_control(self, device_spec) for device_spec in area_spec.get_devices()]


class RaGateway(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, repeater, layout):
		super(RaGateway, self).__init__(house, gateway_instance_name)
		self.devices = {}
		self.areas = {}
		self.repeater = repeater
		self.layout = layout

		# build devices from layout
		self.members = [RaArea(self, area_spec) for area_spec in layout.get_areas()]
		
		# synthesize root area
		# XXX this is vestigial; not used for anything any more; is it useful or should we delete it?
		self.root_area = RaArea(self, ra_layout.Area(0, 'Root Area'))
		self.root_area.members = self.members

		# tell repeater object about the layout (which devices to cache)
		cache = ra_repeater.OutputCache()
		for iid in layout.get_output_ids():
			cache.watch_output(iid)
		for iid in layout.get_device_ids():
			device = layout.get_device(iid)
			cache.watch_device(iid, device.get_button_component_ids(), device.get_led_component_ids())
		cache.subscribe_to_actions(self)
		repeater.bind_cache(cache)
		
	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		assert isinstance(gateway_devid, int)
		iid = int(gateway_devid)
		return self.devices[iid]

	# repeater action callback
	def on_user_action(self, iid, state, refresh):
		logger.debug('repeater action iid %d' % iid)
		device = self.devices[iid]
		device.on_user_action(state, refresh)
	
	# private interface for owned objects to populate node tree
	def _register_device(self, device):
		self.devices[device.iid] = device
		
	def _register_area(self, ra_area):
		self.areas[ra_area.iid] = ra_area
		# match with house area
		sg_area = self.house.get_area_by_name(ra_area.name)
		return sg_area

	# private interface for owned objects to talk to persistence layer
	def _on_device_state_change(self, iid, state, refresh):
		if refresh:
			self.house.persist.init_device_state(self.gateway_id, iid, state)
		else:
			self.house.persist.on_device_state_change(self.gateway_id, iid, state)
		
	def _get_delta_since_change(self, iid):
		return self.house.persist.get_delta_since_change(self.gateway_id, iid)

	def _get_action_count(self, iid, bucket):
		return self.house.persist.get_action_count(self.gateway_id, iid, bucket)

	def _get_time_in_state(self, iid, state, bucket):
		return self.house.persist.get_time_in_state(self.gateway_id, iid, state, bucket)

	# private interface for owned objects to talk to repeater
	def _get_output_level(self, iid):
		return self.repeater.get_output_level(iid)
	
	def _set_output_level(self, iid, level):
		return self.repeater.set_output_level(iid, level)
	
	def _get_button_state(self, iid, bid):
		return self.repeater.get_button_state(iid, bid)
	
	def _set_button_state(self, iid, bid, pressed):
		return self.repeater.set_button_state(iid, bid, pressed)
	
	def _get_led_state(self, iid, lid):
		return self.repeater.get_led_state(iid, lid)
	
	def _set_led_state(self, iid, lid, on):
		return self.repeater.set_led_state(iid, lid, on)
