# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides the common glue between gateway modules, and the
# object model common to the whole system.

import logging

import gateways
import persistence


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

# A note on object instantiation:
# - toplevel framework instantiates a single StargateHouse instance
# - StargateHouse instantiates gateway plugins (StargateGateway instances)
# - each gateway plugin creates 0 or more device instances, which are StargateDevice subclasses
# - the gateway plugin is responsible for mapping the device instances it creates to StargateArea instances
#   (existing, or created on the fly) by asking the house to do so
# - thus, StargateHouse creates StargateArea instances during gateway initialization


class StargateDeviceFilter(object):
	DEVICE_CLASSES = set([ 'control', 'output', 'sensor' ])
	devclass = None # element of DEVICE_CLASSES
	devtype = None # string dependent on devclass
	devstate = None # string dependent on devtype
	
	def __init__(self, devclass = None, devtype = None, devstate = None):
		self.devclass = devclass
		self.devtype = devtype
		self.devstate = devstate
		
	def __str__(self):
		ss = []
		for m in ('devclass', 'devtype', 'devstate'):
			if getattr(self, m) is not None:
				ss.append('%s = "%s"' % (m, getattr(self, m)))
		if len(ss) == 0:
			ss.append('all')
		return '(%s)' % str(', '.join(ss))


class StargateDevice(object):
	# Devices are subclassed into gateway-specific device classes, and created by the gateways.
	# Devices automatically register with their area upon creation. The owning gateway should
	# also be able to look them up.
	
	# XXX: provide some idea of common type/capability information?
	# devclass and devtype are assumed to exist by StargateArea.get_device_type_state_map();
	# they're currently not mentioned by StargateDevice (subclasses add them in their own
	# init and override matches_filter). Should probably pass them down to this __init__
	# and have this matches_filter know about them.
	#
	# Then a lot of the general type/state stuff from LutronDevice/OutputDevice can move
	# here, with a rethinking/cleanup of types and states themselves.
	#
	# XXX the above is becoming less true as I hoist more stuff here from LutronDevice.
	# Rethink, rewrite, recomment.
	
	# XXX default order_states() implementation -- should not be called -- and we need
	# a way for gateways to register this, and for the framework to aggregate them,
	# instead of hardcoding. (Right now demo.py "aggregates" by hardcoding radiora2.)
	@staticmethod
	def order_states(states):
		return states

	# predefined fields that all devices must have, all subclasses must fill in
	house = None            # StargateHouse instance
	area = None             # StargateArea instance, where this device lives
	gateway = None          # StargateGateway instance, the gateway module managing this device
	gateway_devid = None    # String, the id for this device (unique and meaningful only per gateway)
	name = None             # String, human-readable name
	_possible_states = None # Memoization for get_possible_states()
	_possible_actions = None# Memoization for get_possible_actions()

	def __init__(self, house, area, gateway, gateway_devid, name):
		# for now, we require devclass to have been set by subclass; not really good design
		assert self.devclass in StargateDeviceFilter.DEVICE_CLASSES
		assert isinstance(house, StargateHouse)
		assert isinstance(area, StargateArea)
		assert isinstance(gateway, StargateGateway)
		assert isinstance(gateway_devid, str) or isinstance(gateway_devid, unicode)
		assert isinstance(name, str) or isinstance(name, unicode)
		self.house = house
		self.area = area
		self.gateway = gateway
		self.gateway_devid = gateway_devid
		self.name = name
		# register with parent, which also registers with the house (which maintains a house-global lookup table on the unique/stable/int id it gets from the db)
		self.device_id = area.register_device(self)
	
	def matches_filter(self, devfilter):
		if devfilter.devclass is not None and devfilter.devclass != self.devclass:
			return False
		if devfilter.devtype is not None and devfilter.devtype != self.devtype:
			return False
		if devfilter.devstate is not None and not self.is_in_state(devfilter.devstate):
			return False
		return True

	def is_in_state(self, state):
		# special case "age=NNN"
		if state[:4] == 'age=':
			age_max = int(state[4:])
			delta = self.get_delta_since_change()
			if not delta:
				return False
			my_age = delta.days * 86400 + delta.seconds
			return my_age < age_max
		# look for handler named after state
		handler = 'is_' + state
		if hasattr(self, handler):
			return getattr(self, handler)()
		# default answer based on class/type
		if state == 'all' or state == self.devclass or state == self.devtype:
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
			self._possible_states = set([state for state in self.KNOWN_STATES_IN_ORDER if hasattr(self, 'is_' + state)])
		return self._possible_states

	def get_possible_actions(self):
		if not self._possible_actions:
			self._possible_actions = set([state for state in self.KNOWN_STATES_IN_ORDER if hasattr(self, 'be_' + state)])
		return self._possible_actions
	
	def get_delta_since_change(self):
		return self.house.persist.get_delta_since_change(self.gateway.gateway_id, self.gateway_devid)
		
	def get_action_count(self, bucket = 1):
		return self.house.persist.get_action_count(self.gateway.gateway_id, self.gateway_devid, bucket)
		
	# XXX 'levelstate' to distinguish it from level (0-100) or state (string on/off/open/closed/depends on device);
	# 'levelstate' is evaluated in a boolean context, true meaning on/open, false meaning off/closed. In particular,
	# it's allowed to pass a level as the levelstate.
	def get_time_in_state(self, levelstate, bucket = 1):
		return self.house.persist.get_time_in_state(self.gateway.gateway_id, self.gateway_devid, levelstate, bucket)


class StargateArea(object):
	# Areas are a grouping container. They can contain devices and other areas.
	# They are not subclassed by gateway-specific classes; if a gateway has a
	# concept of areas, it can implement that however it wants, and then ask the
	# house to bind to a matching StargateArea. It follows that StargateAreas
	# are always created by the house object, and don't need to be registered
	# with the house object.
	
	name = None             # String, human-readable name
	devices = None          # Flat list of devices in area.
	
	def __init__(self, parent, name):
		assert isinstance(parent, StargateArea)
		assert isinstance(name, str) or isinstance(name, unicode)
		self.parent = parent
		self.house = parent.house
		self.name = name
		self.devices = []
		self.areas = []
		# register with parent, which also registers with the house (which maintains a house-global lookup table on the unique/stable/int id it gets from the db)
		self.area_id = parent.register_area(self)

	def register_device(self, device):
		self.devices.append(device)
		return self.house._register_device(device)
		
	def register_area(self, area):
		if area != self: # special case for the house which is its own parent
			self.areas.append(area)
		return self.house._register_area(area)
	
	# Area/Device/House relation:
	# The house is a tree with devices as leaves and areas as internal nodes (the root node is the house, which is also an area).
	# You can ask any area for a list of areas or devices below it.
	# Devices have a class (control, output, ...), a type (depends on class, but things like keypad/button/switch for input, light/closure for output), and a state (depends on type, on, off, pressed, unpressed, open, closed).
	# Example: control:keypad:pressed; output:shade:open; output:light:off
	# Any device list can be filtered by device class, type, and state.
	# Any area list can be filtered by the device class/type/state, and will return only areas containing devices matching the filter.
	def get_areas_filtered_by(self, devfilter):
		areas = self._get_all_areas_below()
		return filter(lambda a: a._has_device_matching(devfilter), areas)
	
	def get_devices_filtered_by(self, devfilter):
		devs = self._get_all_devices_below()
		return filter(lambda d: d.matches_filter(devfilter), devs)
		
	def _has_device_matching(self, filter):
		return any(dev.matches_filter(filter) for dev in self._get_all_devices_below())
	
	def _get_all_areas_below(self):
		areas = list(self.areas)
		for a in self.areas:
			areas.extend(a._get_all_areas_below())
		return areas

	def _get_all_devices_below(self):
		devs = list(self.devices)
		for a in self.areas:
			devs.extend(a._get_all_devices_below())
		return devs
	
	# XXX what to do with this concept? Revisit class/type/state stuff.
	def get_device_type_state_map(self, devclass = None):
		possible = { 'all': set() } # map from type to set of states
		for dev in self.get_devices_filtered_by(StargateDeviceFilter(devclass = devclass)):
			# make sure type->set mapping exists
			if not possible.has_key(dev.devtype):
				possible[dev.devtype] = set()
			# then add the states for the type
			possible[dev.devtype].update(dev.get_possible_states())
		return possible


class StargateHouse(StargateArea):
	persist = None                  # SgPersistence instance
	gateways_by_name = None         # Map from gateway name to gateway object
	areas_by_name = None            # Map from area name to area object
	devices_by_id = None            # Map from device id to device object
	areas_by_id = None              # Map from area id to area object

	def __init__(self, config):
		# ordering is very important here!
		# need to be mostly complete before calling StargateArea initializer
		self.house = self
		self.persist = persistence.SgPersistence(config.database)
		self.areas_by_name = {}
		self.devices_by_id = {}
		self.areas_by_id = {}
		super(StargateHouse, self).__init__(self, config.house.name)
		# finish initalization of all my fields before calling gateway loader
		# ...
		# gateway loader will cause a lot of stuff to happen
		self.gateways = gateways.load_all(self, config.gateways)
		if not len(self.gateways):
			raise Exception("No gateways were loaded")
	
	def get_device_by_gateway_and_id(self, gateway_id, gateway_device_id):
		gateway = self.gateways[gateway_id]
		return gateway.get_device_by_id(gateway_device_id)
	
	def get_area_by_name(self, area_name):
		# XXX currently creates all areas as direct children of the root area; no facility for deeper nesting
		if not self.areas_by_name.has_key(area_name):
			self.areas_by_name[area_name] = StargateArea(self, area_name)
		return self.areas_by_name[area_name]
		
	def _register_device(self, device):
		did = self.persist.get_device_id(device.gateway.gateway_id, device.gateway_devid)
		self.devices_by_id[did] = device
		return did
	
	def _register_area(self, area):
		aid = self.persist.get_area_id(area.name)
		self.areas_by_id[aid] = area
		return aid

	def get_device_by_id(self, did):
		return self.devices_by_id[did]

	def get_area_by_id(self, aid):
		return self.areas_by_id[aid]
	
	@staticmethod
	def create_devfilter(devclass = None, devtype = None, devstate = None):
		return StargateDeviceFilter(devclass, devtype, devstate)

	@staticmethod
	def parse_devfilter_description(descriptor, devclass = None):
		# allow descriptor to specify devtype or devtype:devstate
		filters = descriptor.split(':')
		devtype = filters[0] if filters[0] else None
		devstate = filters[1] if len(filters) > 1 else None
		return StargateDeviceFilter(devclass, devtype, devstate)

	# XXX find a home for, or rework, this concept
	@staticmethod
	def get_available_common_actions(devices):
		return reduce(set.intersection, map(lambda dev: dev.get_possible_actions(), devices))


class StargateGateway(object):
	# gateways should subclass this
	house = None         # StargateHouse instance
	gateway_id = None    # String, database key (must be unique)
	
	def __init__(self, house, gateway_id):
		assert isinstance(house, StargateHouse)
		assert isinstance(gateway_id, str) or isinstance(gateway_id, unicode)
		self.house = house
		self.gateway_id = gateway_id
		
	# must have:
	# get_device_by_gateway_id(gateway_devid)
