# (c) 2012 Matt Ginzton, matt@ginzton.net



class Device(object):
	# individual RadioRa device -- switch(load), shade, remote, keypad, etc
	def __init__(self, house, iid, zone):
		self.house = house
		self.iid = iid
		self.zone = zone
		house._register_device(iid, self)
		
	# interface to get/set output levels (device scope)
	def get_level(self):
		return self.house._get_output_level(self.iid)
	
	def set_level(self, level):
		self.house._set_output_level(self.iid, level)
		
	def is_on(self):
		return self.get_level() > 0
	
	def is_off(self):
		return self.get_level() == 0

		
class OutputDevice(Device):
	def __init__(self, house, layoutOutput, zone):
		super(OutputDevice, self).__init__(house, layoutOutput.iid, zone)
		self.name = layoutOutput.get_scoped_name()


class DeviceZone(object):
	# grouping container: area or zone containing a set of devices and/or zones
	
	# constructor
	def __init__(self, house, layoutArea):
		self.house = house
		if layoutArea:
			self.iid = layoutArea.iid
			self.name = layoutArea.name
			self.members = [OutputDevice(house, output, self) for output in layoutArea.getOutputs()]
	
	# interface to get/set output levels (zone scope)
	def get_on_devices(self):
		return self.get_devices_matching(Device.is_on)
	
	def get_off_devices(self):
		return self.get_devices_matching(Device.is_off)
		
	def get_all_devices(self):
		return self.get_devices_matching(lambda device: True)
			
	def get_devices_matching(self, filterP = None):
		# build flat list of children
		devs = []
		for m in self.members:
			if isinstance(m, Device):
				devs.append(m)
			else:
				devs.extend(m.get_all_devices())
		# filter list by predicate
		if filterP:
			devs = [dev for dev in devs if filterP(dev)]
		return devs


class House(DeviceZone):
	def __init__(self, repeater, layout):
		super(House, self).__init__(self, None)
		self.devices = {}
		self.verbose = False
		self.repeater = repeater
		self.layout = layout

		# tell repeater about the layout (just what output devices to query)
		repeater.set_outputs_to_cache(layout.get_all_output_ids())
		
		# build house from layout
		self.iid = -1
		self.name = 'Global'
		self.members = [DeviceZone(self, area) for area in layout.getAreas()]

	# public interface to clients
	def set_verbose(self, verbose):
		self.verbose = verbose

	def get_device_by_iid(self, iid):
		return self.devices[iid]

	# private interface for owned objects to talk to repeater
	def _register_device(self, iid, device):
		self.devices[iid] = device

	def _get_output_level(self, iid):
		return self.repeater.get_output_level(iid)
	
	def _set_output_level(self, iid, level):
		return self.repeater.set_output_level(iid, level)
	