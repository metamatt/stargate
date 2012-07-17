# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# High-level interface to Lutron RadioRa2 system.

import ra_repeater


class LutronDevice(object):
	# Individual RadioRa device -- includes both controllable outputs (what Lutron calls an "output")
	# and we will subclass as "OutputDevice") and inputs/controls (what Lutron calls an "input", I
	# would typically call a "keypad", and we will subclass as "ControlDevice").

	house = None
	area = None
	iid = None
	name = None
	devclass = None
	devtype = None
	
	def __init__(self, devclass, area, iid, name):
		self.devclass = devclass
		self.house = area.house
		self.area = area
		self.iid = iid
		self.name = name
		self._possible_states = None
		self._possible_actions = None
		self.house._register_device(self)

	def is_in_state(self, state):
		handler = 'is_' + state
		if hasattr(self, handler):
			return getattr(self, handler)()
		if state == 'all' or state == self.devclass or state == self.devtype:
			return True
		return False

	# XXX how many of these belong here vs OutputDevice? Certainly not get_level
	def get_current_states(self):
		return [state for state in self.get_possible_states() if self.is_in_state(state)]

	def get_possible_states(self):
		if not self._possible_states:
			self._possible_states = set([state for state in OutputDevice.KNOWN_STATES_IN_ORDER if hasattr(self, 'is_' + state)])
		return self._possible_states

	def get_possible_actions(self):
		if not self._possible_actions:
			self._possible_actions = set([state for state in OutputDevice.KNOWN_STATES_IN_ORDER if hasattr(self, 'be_' + state)])
		return self._possible_actions


class OutputDevice(LutronDevice):
	# Common device subclass for controllable outputs (lights, shades, appliances).

	KNOWN_STATES_IN_ORDER = [ 'output', 'light', 'closed', 'off', 'half', 'on', 'shade', 'open', 'contactclosure', 'control', 'keypad', 'all' ]
	@staticmethod
	def order_states(states):
		return [state for state in OutputDevice.KNOWN_STATES_IN_ORDER if state in states]

	def __init__(self, area, device_spec):
		super(OutputDevice, self).__init__('output', area, device_spec.iid, device_spec.name)
		self.level_step = 100

	# interface to get/set output levels (device scope)
	def get_level(self):
		return self.house._get_output_level(self.iid)

	def set_level(self, level):
		self.house._set_output_level(self.iid, level)

	def go_to_state(self, state):
		handler = 'be_' + state
		if not hasattr(self, handler):
			return False
		getattr(self, handler)()
		return True


class SwitchedOutput(OutputDevice):
	def __init__(self, area, device_spec):
		super(SwitchedOutput, self).__init__(area, device_spec)
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
	def __init__(self, area, device_spec):
		super(DimmedOutput, self).__init__(area, device_spec)
		self.level_step = 1

	def be_half(self):
		self.set_level(50)


class ShadeOutput(OutputDevice):
	def __init__(self, area, device_spec):
		super(ShadeOutput, self).__init__(area, device_spec)
		self.devtype = 'shade'
		self.level_step = 1
	
	def be_half(self):
		self.set_level(50)

	# XXX should we define "partially open", "fully open", "partially closed", "fully closed"?
	# and a half-open shade is both partially open and closed? Otherwise, what is it?
	def is_closed(self):
		return self.get_level() == 0
	
	def be_closed(self):
		self.set_level(0)

	def is_open(self):
		return self.get_level() >= 100 # sometimes set to 100.01!

	def be_open(self):
		self.set_level(100)


class ContactClosureOutput(OutputDevice):
	def __init__(self, area, device_spec):
		super(ContactClosureOutput, self).__init__(area, device_spec)
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


def create_device_for_output(area, output_spec):
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
	except Exception as ex: # XXX fall back on default/generic case
		print ex
		cls = OutputDevice

	return cls(area, output_spec)


class ControlDevice(LutronDevice):
	# Common device subclass for controls (keypads, remotes, repeater/receiver buttons).

	def __init__(self, area, device_spec):
		super(ControlDevice, self).__init__('control', area, device_spec.iid, device_spec.name)


class KeypadButton(object):
	def __init__(self, device, button_cid, label, led_cid):
		self.device = device
		self.button_cid = button_cid
		self.label = label
		self.led_cid = led_cid

	def has_led(self):
		return self.led_cid is not None

	def get_button_state(self):
		return self.device.house._get_button_state(self.device.iid, self.button_cid)

	def get_led_state(self):
		return self.device.house._get_led_state(self.device.iid, self.led_cid)
		
	def set_button_state(self, pressed):
		self.device.house._set_button_state(self.device.iid, self.button_cid, pressed)
		
	def set_led_state(self, on):
		self.device.house._set_led_state(self.device.iid, self.led_cid, on)


class KeypadDevice(ControlDevice):
	def __init__(self, area, device_spec):
		super(KeypadDevice, self).__init__(area, device_spec)
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


def create_device_for_control(area, device_spec):
	# Static factory for correct ControlDevice subclass matching Lutron DeviceType.
	# Valid/known devicetypes: SEETOUCH_KEYPAD, SEETOUCH_TABLETOP_KEYPAD, SEETOUCH_HYBRID_KEYPAD,
	# PICO_KEYPAD, VISOR_CONTROL_RECEIVER, MAIN_REPEATER. But they all just act like keypads.
	cls = KeypadDevice
	return cls(area, device_spec)


class DeviceArea(object):
	# grouping container: area containing a set of devices and/or other areas
	# (Matches Lutron's "area" concept).
	
	# XXX should clean up constructor arguments, deal with nested areas, and avoid
	# needing to pass the house to nested areas. This should just take a "parent"
	# argument.
	def __init__(self, house, area_spec):
		self.house = house
		if area_spec:
			self.iid = area_spec.iid
			self.name = area_spec.name
			self.members = [create_device_for_output(self, output_spec) for output_spec in area_spec.get_outputs()] + [
						    create_device_for_control(self, device_spec) for device_spec in area_spec.get_devices()]
			house._register_area(self)

	def _children_of_class(self, cls):
		# build flat list of children
		devs = []
		for m in self.members:
			if isinstance(m, cls):
				devs.append(m)
			if isinstance(m, DeviceArea):
				devs.extend(m._children_of_class(cls))
		return devs

	# filters
	def has_device_in_state(self, state):
		return any(dev.is_in_state(state) for dev in self.get_all_devices())

	# interface to enumerate contained devices and areas
	def get_all_devices(self, devclass = 'both'):
		class_for_devclass = { 'in': ControlDevice, 'out': OutputDevice, 'both': LutronDevice }
		return self._children_of_class(class_for_devclass[devclass])

	def get_devices_filtered_by(self, filters = [], devclass = 'both'):
		devs = self.get_all_devices(devclass)
		for state in filters:
			devs = filter(lambda dev: dev.is_in_state(state), devs)
		return devs

	def get_all_areas(self):
		return self._children_of_class(DeviceArea)

	def get_areas_filtered_by(self, filters):
		areas = self.get_all_areas()
		for state in filters:
			areas = filter(lambda area: area.has_device_in_state(state), areas)
		return areas

	def get_device_type_state_map(self):
		possible = { 'all': set() }
		for dev in self.get_all_devices():
			if not possible.has_key(dev.devtype):
				possible[dev.devtype] = set()
			possible[dev.devtype].update(dev.get_possible_states())
		return possible

	@staticmethod
	def get_supported_actions(devices):
		return reduce(set.intersection, map(lambda dev: dev.get_possible_actions(), devices))


class House(DeviceArea):
	def __init__(self, repeater, layout):
		super(House, self).__init__(self, None)
		self.devices = {}
		self.areas = {}
		self.verbose = False
		self.repeater = repeater
		self.layout = layout

		# tell repeater about the layout (just what output devices to query)
		cache = ra_repeater.OutputCache()
		for iid in layout.get_output_ids():
			cache.watch_output(iid)
		for iid in layout.get_device_ids():
			device = layout.get_device(iid)
			cache.watch_device(iid, device.get_button_component_ids(), device.get_led_component_ids())
		repeater.reset_cache(cache)
		
		# build house from layout
		self.iid = -1
		self.name = 'Global'
		self.members = [DeviceArea(self, area_spec) for area_spec in layout.get_areas()]

	# public interface to clients
	def set_verbose(self, verbose):
		self.verbose = verbose

	def get_device_by_iid(self, iid):
		return self.devices[iid]

	def get_devicearea_by_iid(self, iid):
		return self.areas[iid]

	# private interface for owned objects to talk to repeater
	def _register_device(self, device):
		self.devices[device.iid] = device
		
	def _register_area(self, area):
		self.areas[area.iid] = area

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
