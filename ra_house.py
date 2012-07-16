# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# High-level interface to Lutron RadioRa2 system.


class BaseDevice(object):
	# Individual RadioRa device -- includes both controllable outputs (what Lutron calls an "output")
	# and we will subclass as "OutputDevice") and inputs/controls (what Lutron calls an "input", I
	# would typically call a "keypad", and we will subclass as "ControlDevice").

	house = None
	zone = None
	iid = None
	name = None
	
	def __init__(self, zone, iid, name):
		self.house = zone.house
		self.zone = zone
		self.iid = iid
		self.name = name


class OutputDevice(BaseDevice):
	# Common device subclass for controllable outputs (lights, shades, appliances).

	KNOWN_STATES_IN_ORDER = ['light', 'closed', 'off', 'half', 'on', 'shade', 'open', 'contactclosure', 'all']
	@staticmethod
	def order_states(states):
		return [state for state in OutputDevice.KNOWN_STATES_IN_ORDER if state in states]

	def __init__(self, zone, output):
		super(OutputDevice, self).__init__(zone, output.iid, output.name)
		self.type = None
		self.level_step = 100
		self._possible_states = None
		self._possible_actions = None
		self.house._register_device(self)
		
	# interface to get/set output levels (device scope)
	def get_level(self):
		return self.house._get_output_level(self.iid)
	
	def set_level(self, level):
		self.house._set_output_level(self.iid, level)
	
	def is_in_state(self, state):
		handler = 'is_' + state
		if hasattr(self, handler):
			return getattr(self, handler)()
		if state == 'all':
			return True
		if state == self.type:
			return True
		return False

	def go_to_state(self, state):
		handler = 'be_' + state
		if not hasattr(self, handler):
			return False
		getattr(self, handler)()
		return True

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


class SwitchedOutput(OutputDevice):
	def __init__(self, zone, output):
		super(SwitchedOutput, self).__init__(zone, output)
		self.type = 'light'

	def is_on(self):
		return self.get_level() > 0

	def be_on(self):
		self.set_level(100)

	def is_off(self):
		return self.get_level() == 0
		
	def be_off(self):
		self.set_level(0)


class DimmedOutput(SwitchedOutput):
	def __init__(self, zone, output):
		super(DimmedOutput, self).__init__(zone, output)
		self.level_step = 1

	def be_half(self):
		self.set_level(50)


class ShadeOutput(OutputDevice):
	def __init__(self, zone, output):
		super(ShadeOutput, self).__init__(zone, output)
		self.type = 'shade'
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
	def __init__(self, zone, output):
		super(ContactClosureOutput, self).__init__(zone, output)
		self.pulsed = output.get_type() == 'CCO_PULSED'
		self.type = 'contactclosure'
		
	def is_closed(self):
		return self.get_level() == 0

	def be_closed(self):
		self.set_level(0)

	def is_open(self):
		return self.get_level() > 0

	def be_open(self):
		self.set_level(100)



def create_device_for_output(zone, output):
	# Static factory for correct OutputDevice subclass matching Lutron device type.
	map_lutron_output_to_class = {
		"INC": DimmedOutput,
		"NON_DIM": SwitchedOutput,
		"SYSTEM_SHADE": ShadeOutput,
		"CCO_PULSED": ContactClosureOutput,
		"CCO_MAINTAINED": ContactClosureOutput,
	}
	
	try:
		cls = map_lutron_output_to_class[output.get_type()]
	except Exception as ex: # XXX fall back on default/generic case
		print ex
		cls = OutputDevice

	return cls(zone, output)


class DeviceZone(object):
	# grouping container: zone containing a set of devices and/or other zones
	# (Matches Lutron's "area" concept).
	
	# XXX should clean up constructor arguments, deal with nested areas, and avoid
	# needing to pass the house to nested areas. This should just take a "parent"
	# argument.
	def __init__(self, house, area):
		self.house = house
		if area:
			self.iid = area.iid
			self.name = area.name
			self.members = [create_device_for_output(self, output) for output in area.get_outputs()]
			house._register_zone(self)

	def _children_of_type(self, cls):
		# build flat list of children
		devs = []
		for m in self.members:
			if isinstance(m, cls):
				devs.append(m)
			if isinstance(m, DeviceZone):
				devs.extend(m._children_of_type(cls))
		return devs

	# filters
	def has_device_in_state(self, state):
		return any(dev.is_in_state(state) for dev in self.get_all_devices())

	# interface to enumerate contained devices and areas
	def get_all_devices(self):
		return self._children_of_type(OutputDevice)

	def get_devices_filtered_by(self, filters):
		devs = self.get_all_devices()
		for state in filters:
			devs = filter(lambda dev: dev.is_in_state(state), devs)
		return devs

	def get_all_areas(self):
		return self._children_of_type(DeviceZone)

	def get_areas_filtered_by(self, filters):
		areas = self.get_all_areas()
		for state in filters:
			areas = filter(lambda area: area.has_device_in_state(state), areas)
		return areas

	def get_device_type_state_map(self):
		possible = { 'all': set() }
		for dev in self.get_all_devices():
			if not possible.has_key(dev.type):
				possible[dev.type] = set()
			possible[dev.type].update(dev.get_possible_states())
		return possible

	@staticmethod
	def get_supported_actions(devices):
		return reduce(set.intersection, map(lambda dev: dev.get_possible_actions(), devices))
		

class House(DeviceZone):
	def __init__(self, repeater, layout):
		super(House, self).__init__(self, None)
		self.devices = {}
		self.zones = {}
		self.verbose = False
		self.repeater = repeater
		self.layout = layout

		# tell repeater about the layout (just what output devices to query)
		repeater.set_outputs_to_cache(layout.get_output_ids())
		
		# build house from layout
		self.iid = -1
		self.name = 'Global'
		self.members = [DeviceZone(self, area) for area in layout.get_areas()]

	# public interface to clients
	def set_verbose(self, verbose):
		self.verbose = verbose

	def get_device_by_iid(self, iid):
		return self.devices[iid]
		
	def get_devicezone_by_iid(self, iid):
		return self.zones[iid]

	# private interface for owned objects to talk to repeater
	def _register_device(self, device):
		self.devices[device.iid] = device
		
	def _register_zone(self, zone):
		self.zones[zone.iid] = zone

	def _get_output_level(self, iid):
		return self.repeater.get_output_level(iid)
	
	def _set_output_level(self, iid, level):
		return self.repeater.set_output_level(iid, level)
	