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
	
	# queries
	QUERIES = [ 'on', 'off', 'open', 'closed', 'light', 'shade', 'contactclosure', 'all' ]

	def is_dummy(self):
		return False

	def is_all(self):
		return True

# Add the rest of the base-class fallthrough query handles to the Device class
for query_name in Device.QUERIES:
	method_name = 'is_' + query_name
	if not hasattr(Device, method_name):
		setattr(Device, method_name, Device.is_dummy)

		
class OutputDevice(Device):
	def __init__(self, house, zone, output):
		super(OutputDevice, self).__init__(house, zone, output.iid)
		self.name = output.get_scoped_name()


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
	
	def is_contactclosure(self):
		return True


def create_device_for_output(house, zone, output):
	map_lutron_output_to_class = {
		"INC": DimmedOutput,
		"NON_DIM": SwitchedOutput,
		"SYSTEM_SHADE": ShadeOutput,
		"CCO_PULSED": ContactClosureOutput,
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

	# queries
	def has_general(self, query_name):
		return any(getattr(dev, 'is_' + query_name)() for dev in self.get_all_devices())
	# After this class is defined, we will autogenerate a bunch of specializations of this

	# interface to enumerate contained devices and areas
	def get_all_devices(self):
		return self._children_of_type(Device)

	def get_devices_matching(self, filterP):
		return filter(filterP, self.get_all_devices())
		
	def get_devices_in_state(self, state):
		def inStateP(state):
			def device_is_in_state(dev, state):
				state_pred = 'is_' + state
				try:
					return getattr(dev, state_pred)()
				except Exception as ex:
					print ex
					return False
			return lambda dev: device_is_in_state(dev, state)
		return self.get_devices_matching(inStateP(state))

	def get_all_areas(self):
		return self._children_of_type(DeviceZone)

	def get_areas_matching(self, filterP):
		return filter(filterP, self.get_all_areas())

	def get_areas_with_devices(self, childtype):
		def hasChildP(childtype):
			def area_has_child(area, childtype):
				type_pred = 'has_' + childtype
				try:
					return getattr(area, type_pred)()
				except Exception as ex:
					print ex
					return False
			return lambda area: area_has_child(area, childtype)
		return self.get_areas_matching(hasChildP(childtype))

# Automatically wrap the "is" device queries as "has" zone queries
for query_name in Device.QUERIES:
	# Note lambda-takes-extra-arg-with-default hack to capture current *value* of query_name
	setattr(DeviceZone, 'has_' + query_name, lambda self, query_name = query_name: DeviceZone.has_general(self, query_name))


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
	