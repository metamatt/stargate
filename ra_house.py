# (c) 2012 Matt Ginzton, matt@ginzton.net



class Device(object):
	# individual RadioRa device -- switch(load), shade, remote, keypad, etc
	# XXX the split between this and OutputDevice is arbitrary right now, I'm still figuring out where it lies
	def __init__(self, house, zone, iid):
		self.house = house
		self.zone = zone
		self.iid = iid
		house._register_device(iid, self)
		self.statemap = {}
		
	# interface to get/set output levels (device scope)
	def get_level(self):
		return self.house._get_output_level(self.iid)
	
	def set_level(self, level):
		self.house._set_output_level(self.iid, level)
	
	def is_in_state(self, state):
		if self.statemap.has_key(state):
			handler = self.statemap[state]
			if hasattr(handler, '__call__'):
				return handler()
			return handler
		if state == 'all':
			return True
		if state == self.type:
			return True
		return False
		
	def get_current_states(self):
		return [state for state in self.get_possible_states() if self.is_in_state(state)]
	
	def get_possible_states(self):
		return self.statemap.keys() + ['all'] + ([ self.type ] if self.type else [])


class OutputDevice(Device):
	def __init__(self, house, zone, output):
		super(OutputDevice, self).__init__(house, zone, output.iid)
		self.name = output.name


class SwitchedOutput(OutputDevice):
	def __init__(self, house, zone, output):
		super(SwitchedOutput, self).__init__(house, zone, output)
		self.type = 'light'
		self.statemap = {
			'on': self.is_on,
			'off': self.is_off,
		}

	def is_on(self):
		return self.get_level() > 0

	def is_off(self):
		return self.get_level() == 0


class DimmedOutput(SwitchedOutput):
	def __init__(self, house, zone, output):
		super(DimmedOutput, self).__init__(house, zone, output)


class ShadeOutput(OutputDevice):
	def __init__(self, house, zone, output):
		super(ShadeOutput, self).__init__(house, zone, output)
		self.type = 'shade'
		self.statemap = {
			'closed': self.is_closed,
			'open': self.is_open,
		}

	# XXX should we define "partially open", "fully open", "partially closed", "fully closed"?
	# and a half-open shade is both partially open and closed? Otherwise, what is it?
	def is_closed(self):
		return self.get_level() == 0

	def is_open(self):
		return self.get_level() >= 100 # sometimes set to 100.01!


class ContactClosureOutput(OutputDevice):
	def __init__(self, house, zone, output):
		super(ContactClosureOutput, self).__init__(house, zone, output)
		self.pulsed = output.get_type() == 'CCO_PULSED'
		# XXX should CCOs expose states named "open/closed" or "on/off" or what?
		self.type = 'contactclosure'


def create_device_for_output(house, zone, output):
	map_lutron_output_to_class = {
		"INC": DimmedOutput,
		"NON_DIM": SwitchedOutput,
		"SYSTEM_SHADE": ShadeOutput,
		"CCO_PULSED": ContactClosureOutput,
		"CCO_MAINTAINED": ContactClosureOutput,
	}
	
	try:
		cls = map_lutron_output_to_class[output.get_type()]
	except Exception as ex:
		print ex
		cls = OutputDevice

	return cls(house, zone, output)


class DeviceZone(object):
	# grouping container: area or zone containing a set of devices and/or zones
	
	# constructor
	def __init__(self, house, area):
		self.house = house
		if area:
			self.iid = area.iid
			self.name = area.name
			self.members = [create_device_for_output(house, self, output) for output in area.get_outputs()]
			house._register_zone(self.iid, self)
	
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
		return self._children_of_type(Device)

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
	
	def get_relevant_filters(self):
		possible = set()
		for dev in self.get_all_devices():
			possible.update(dev.get_possible_states())
		#return list(possible)
		order = ['light', 'off', 'on', 'shade', 'open', 'closed', 'contactclosure', 'all']
		return [state for state in order if state in possible]


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
	def _register_device(self, iid, device):
		self.devices[iid] = device
		
	def _register_zone(self, iid, zone):
		self.zones[iid] = zone

	def _get_output_level(self, iid):
		return self.repeater.get_output_level(iid)
	
	def _set_output_level(self, iid, level):
		return self.repeater.set_output_level(iid, level)
	