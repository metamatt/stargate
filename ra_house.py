# (c) 2012 Matt Ginzton, matt@ginzton.net



class Device(object):
	# individual RadioRa device -- switch(load), shade, remote, keypad, etc
	# XXX the split between this and OutputDevice is arbitrary right now, I'm still figuring out where it lies
	def __init__(self, house, zone, iid):
		self.house = house
		self.zone = zone
		self.iid = iid
		house._register_device(iid, self)
		
	# interface to get/set output levels (device scope)
	def get_level(self):
		return self.house._get_output_level(self.iid)
	
	def set_level(self, level):
		self.house._set_output_level(self.iid, level)
	
	# filters
	FILTERS = [ 'on', 'off', 'open', 'closed', 'light', 'shade', 'contactclosure', 'all' ]

	def is_all(self):
		return True
		
	@classmethod
	def _add_generated_methods(cls):
		# Add the rest of the base-class fallthrough filter handlers
		for filter_name in Device.FILTERS:
			method_name = 'is_' + filter_name
			if not hasattr(cls, method_name):
				setattr(cls, method_name, lambda dev: False)

Device._add_generated_methods()

		
class OutputDevice(Device):
	def __init__(self, house, zone, output):
		super(OutputDevice, self).__init__(house, zone, output.iid)
		self.name = output.name


class SwitchedOutput(OutputDevice):
	def __init__(self, house, zone, output):
		super(SwitchedOutput, self).__init__(house, zone, output)

	def is_light(self):
		return True

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

	def is_shade(self):
		return True

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
	
	def is_contactclosure(self):
		return True


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
	def has_general(self, filter_name):
		return any(getattr(dev, 'is_' + filter_name)() for dev in self.get_all_devices())
	# After this class is defined, we will autogenerate a bunch of specializations of this
	# by invoking the following:
	@classmethod
	def _add_generated_methods(cls):
		# Automatically wrap the "is" device filters as "has" zone filters
		for filter_name in Device.FILTERS:
			# Note lambda-takes-extra-arg-with-default hack to capture current *value* of filter_name
			setattr(cls, 'has_' + filter_name, lambda self, filter_name = filter_name: DeviceZone.has_general(self, filter_name))

	# interface to enumerate contained devices and areas
	def get_all_devices(self):
		return self._children_of_type(Device)

	def get_devices_filtered_by(self, filters):
		def inStateP(state):
			def device_is_in_state(dev, state):
				state_pred = 'is_' + state
				if hasattr(dev, state_pred):
					return getattr(dev, state_pred)()
				return False
			return lambda dev: device_is_in_state(dev, state)
		devs = self.get_all_devices()
		for state in filters:
			devs = filter(inStateP(state), devs)
		return devs

	def get_all_areas(self):
		return self._children_of_type(DeviceZone)

	def get_areas_filtered_by(self, filters):
		def hasChildP(childtype):
			def area_has_child(area, childtype):
				type_pred = 'has_' + childtype
				if hasattr(area, type_pred):
					return getattr(area, type_pred)()
				return False
			return lambda area: area_has_child(area, childtype)
		areas = self.get_all_areas()
		for state in filters:
			areas = filter(hasChildP(state), areas)
		return areas
	
	def get_relevant_filters(self):
		# XXX need to have concept of filters that are active now, those that aren't but could be, and those that just aren't
		# tie this into code that knows how many of each?
		# also want reasonable way to sort the resulting filters
		return Device.FILTERS

DeviceZone._add_generated_methods()


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
	