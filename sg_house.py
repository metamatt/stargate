# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides the common glue between gateway modules, and the
# object model common to the whole system.

import datetime
import logging

import connections
import events
import gateways
import notify
import persistence
import reports
import timer


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
	DEVICE_CLASSES = ( 'control', 'sensor', 'output' )
	
	def __init__(self, devclass = None, devtype = None, devstate = None):
		# devclass: element of DEVICE_CLASSES
		self.devclass = devclass if devclass != 'all' else None
		assert not self.devclass or self.devclass in StargateDeviceFilter.DEVICE_CLASSES
		# devtype: string, legal values dependent on devclass
		self.devtype = devtype if devtype != 'all' else None
		# devstate: string, legal values dependent on devtype
		self.devstate = devstate if devtype != 'all' else None
		
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
	
	# XXX Set by subclass before calling base class constructor
	# XXX These are often implemented as subclass class attributes, so we better not assign
	# to them in our constructor.
	# devclass = None				# String, device class (must be known to StargateDeviceFilter.DEVICE_CLASSES)
	# devtype = None				# String, device type (meaning depends on devclass)
	# possible_states = ()			# List of strings, possible states (meaning depends on devtype)

	def __init__(self, house, area, gateway, gateway_devid, name):
		self.house = house					# StargateHouse instance
		self.area = area					# StargateArea instance, where this device lives
		self.gateway = gateway				# StargateGateway instance, the gateway module managing this device
		self.gateway_devid = gateway_devid	# String, the id for this device (unique and meaningful only per gateway)
		self.name = name					# String, human-readable name
		self._possible_states = None		# Memoization for get_possible_states()
		self._possible_actions = None		# Memoization for get_possible_actions()
		# for now, we require self.devclass to have been set by subclass before calling
		# this superclass constructor; not really good design. Also, in some cases
		# self.devclass is actually a lookup against a class variable and not an instance
		# variable, which is a little hacky.
		assert self.devclass in StargateDeviceFilter.DEVICE_CLASSES
		assert isinstance(house, StargateHouse)
		assert isinstance(area, StargateArea)
		assert isinstance(gateway, StargateGateway)
		assert isinstance(gateway_devid, str) or isinstance(gateway_devid, unicode)
		assert isinstance(name, str) or isinstance(name, unicode)
		# register with parent, which also registers with the house (which maintains a house-global lookup table on the unique/stable/int id it gets from the db)
		self.device_id = area.register_device(self)
	
	def get_internal_name(self):
		return '%s:%s' % (self.gateway.gateway_id, self.gateway_devid)

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
			age_limit = datetime.timedelta(seconds = int(state[4:]))
			return self.get_action_count(age_limit) > 0
		# look for handler named after state
		handler = 'is_' + state
		if hasattr(self, handler):
			return getattr(self, handler)()
		# default answer based on class/type
		if state == self.devclass or state == self.devtype:
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

	def get_child_ids(self):
		return []

	# XXX see if these still make sense
	def get_possible_states(self):
		if not self._possible_states:
			self._possible_states = set([state for state in self.possible_states if hasattr(self, 'is_' + state)])
		return self._possible_states

	def get_possible_actions(self):
		if not self._possible_actions:
			self._possible_actions = set([state for state in self.possible_states if hasattr(self, 'be_' + state)])
		return self._possible_actions
	
	def get_delta_since_change(self):
		return self.house.persist.get_delta_since_change(self.device_id)
		
	def get_action_count(self, age_limit = None):
		# allow callers to pass age_limit as a timedelta, but also allow templates to pass it as time in seconds
		if isinstance(age_limit, int):
			age_limit = datetime.timedelta(seconds = age_limit)
		return self.house.persist.get_action_count(self.device_id, age_limit)
		
	# XXX 'levelstate' to distinguish it from level (0-100) or state (string on/off/open/closed/depends on device);
	# 'levelstate' is evaluated in a boolean context, true meaning on/open, false meaning off/closed. In particular,
	# it's allowed to pass a level as the levelstate.
	def get_time_in_state(self, levelstate):
		return self.house.persist.get_time_in_state(self.device_id, levelstate)

	def get_recent_events(self, count = 10):
		return self.house.persist.get_recent_events(self.device_id, count)


class StargateArea(object):
	# Areas are a grouping container. They can contain devices and other areas.
	# They are not subclassed by gateway-specific classes; if a gateway has a
	# concept of areas, it can implement that however it wants, and then ask the
	# house to bind to a matching StargateArea. It follows that StargateAreas
	# are always created by the house object, and don't need to be registered
	# with the house object.
	
	def __init__(self, parent, name):
		assert isinstance(parent, StargateArea)
		assert isinstance(name, str) or isinstance(name, unicode)
		self.parent = parent
		self.house = parent.house
		self.name = name			# String, human-readable name
		self.devices = []			# Flat list of devices in area.
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

	def get_recent_events(self, count = 10):
		dev_ids = [dev.device_id for dev in self._get_all_devices_below(force_enumerate = True)]
		return self.house.persist.get_recent_events(dev_ids, count)
	
	# Area/Device/House relation:
	# The house is a tree with devices as leaves and areas as internal nodes (the root node is the house, which is also an area).
	# You can ask any area for a list of areas or devices below it.
	# Devices have a class (control, output, ...), a type (depends on class, but things like keypad/button/switch for input, light/closure for output), and a state (depends on type, on, off, pressed, unpressed, open, closed).
	# Example: control:keypad:pressed; output:shade:open; output:light:off
	# Any device list can be filtered by device class, type, and state.
	# Any area list can be filtered by the device class/type/state, and will return only areas containing devices matching the filter.
	def get_areas_filtered_by(self, devfilter):
		areas = self._get_all_areas_below()
		areas.append(self)
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

	def _get_all_devices_below(self, force_enumerate = False):
		devs = [d for d in self.devices if force_enumerate or not hasattr(d, 'hide_from_enumeration')]
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
	def __init__(self, config):
		# ordering is very important here!
		# For one, we need to be mostly complete before calling StargateArea initializer
		# For two, try to keep intermodule dependencies to a minimum. For now we're initializing
		# them in dependency order, and passing the dependencies in explicitly so they don't
		# need or get a dependency back to this house object.
		self.house = self											# SgHouse instance as SgArea member (we call super.__init__ later, below)
		self.events = events.SgEvents()                             # SgEvents instance
		self.timer = timer.SgTimer()                                # SgTimer instance
		self.notify = notify.SgNotify(config.notifications)         # SgNotify instance
		self.persist = persistence.SgPersistence(config.database,   # SgPersistence instance
			                                     self.events, self.timer)
		if config.get('reporting'):
			self.reports = reports.SgReporter(config.reporting,     # SgReporter instance
				                              self.timer, self.notify)
		self.watchdog = connections.SgWatchdog()                    # SgWatchdog instance
		self.areas_by_name = {}										# Map from area name to area object
		self.devices_by_id = {}										# Map from device id to device object
		self.areas_by_id = {}										# Map from area id to area object
		self.devtype_order_by_devclass = {}  						# Map from devclass to list of devtype values, in sort order
		self.devstate_order_by_tc = {}       						# Map from devclass:devtype to list of devstate values, in sort order
		super(StargateHouse, self).__init__(self, config.house.name)

		# XXX should we start watchdog before or after loading gateways?
		# XXX if gateway loading blocks (example, synther looking for dsc device status) we're dead in the water.
		# Should probably disallow gateway loading from blocking operations; at least code synther not to do it.
		self.watchdog.start()

		# finish initalization of all my fields before calling gateway loader
		# ...
		# gateway loader will cause a lot of stuff to happen
		# including populating self.gateways in this object
		gateways.load_all(self, config.gateways)
		if not len(self.gateways):
			raise Exception("No gateways were loaded")
		logger.info('Stargate is alive')
	
	def get_device_by_gateway_and_id(self, gateway_id, gateway_device_id):
		gateway = self.gateways[gateway_id]
		return gateway.get_device_by_gateway_id(gateway_device_id)
	
	def get_area_by_name(self, area_name):
		# XXX currently creates all areas as direct children of the root area; no facility for deeper nesting
		if not self.areas_by_name.has_key(area_name):
			self.areas_by_name[area_name] = StargateArea(self, area_name)
		return self.areas_by_name[area_name]
		
	def _register_device(self, device):
		did = self.persist.get_device_id(device.gateway.gateway_id, device.gateway_devid)
		self.devices_by_id[did] = device
		self._add_devtype_for_ordering(device.devclass, device.devtype)
		self._add_devstates_for_ordering(device.devclass, device.devtype, device.possible_states)
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

	@staticmethod
	def get_available_common_actions(devices):
		return reduce(set.intersection, map(lambda dev: dev.get_possible_actions(), devices))

	def _add_devtype_for_ordering(self, devclass, devtype):
		# make sure class key exists
		if not self.devtype_order_by_devclass.has_key(devclass):
			self.devtype_order_by_devclass[devclass] = []
		# organize by class (control|sensor|output), then by type (alphabetical?)
		if devtype not in self.devtype_order_by_devclass[devclass]:
			self.devtype_order_by_devclass[devclass].append(devtype)
			self.devtype_order_by_devclass[devclass].sort() # XXX: just alphabetical for now; do these have a natural order better than this?

	def _add_devstates_for_ordering(self, devclass, devtype, devstates):
		# Allow multiple calls for same devclass/devtype, each supplying a partial order of devstates, as long as the multiple partial orders don't conflict.
		# That is, one output:light can say "on off" and another can say "on half off", but the second one can't say "off half on". In the event someone
		# breaks this rule, we complain and tie goes to whoever was first.
		tc = '%s:%s' % (devclass, devtype)
		
		# Merge new states into existing states
		#
		# Temporary algorithm:
		# - iterate the incoming states; for each state see if we've already got it in the existing state order list
		# - if yes: add the front of the existing state order list (up to that point) to the new state order list
		# - if no: add the newly seen state to the new state order list
		#
		# XXX this is a hacky incomplete way of doing this; depends on some overlap between each device's idea of states;
		# a correct implementation would need to keep all the constraints around, and do a topological sort when the
		# constraints change.
		old_order = self.devstate_order_by_tc[tc] if self.devstate_order_by_tc.has_key(tc) else []
		new_order = []
		for state in devstates:
			try:
				old_index = old_order.index(state) + 1 # index inclusive of the sought state
				# assuming that worked, we slice that much off the old list, and add it to the new list
				new_order.extend(old_order[:old_index])
				old_order = old_order[old_index:]
			except ValueError:
				# this state is new; append it at this point in the new list
				new_order.append(state)
		self.devstate_order_by_tc[tc] = new_order
	
	def order_device_states(self, states, devclass = None, devtype = None):
		# get list of devclasses whose devtypes to iterate
		if devclass and devclass != 'device':
			classes = [devclass]
		else:
			classes = StargateDeviceFilter.DEVICE_CLASSES
		# iterate devclass list to build list of devtypes
		tcs = []
		for dc in classes:
			if self.devtype_order_by_devclass.has_key(dc):
				for dt in self.devtype_order_by_devclass[dc]:
					if dt is None or dt == devtype:
						tcs.append('%s:%s' % (dc, dt))
		# iterate flattened class/type list to build list of devstates
		order = []
		for tc in tcs:
			order.extend(self.devstate_order_by_tc[tc])
		order.append('all')
		# order the input list by the criteria we just built
		return [state for state in order if state in states]
		
	def order_device_types(self, types, devclass = None):
		# get list of devclasses whose devtypes to iterate
		if devclass and devclass != 'device':
			classes = [devclass]
		else:
			classes = StargateDeviceFilter.DEVICE_CLASSES
		# iterate devclass list to build list of devtypes
		order = []
		for dc in classes:
			if self.devtype_order_by_devclass.has_key(dc):
				order.extend(self.devtype_order_by_devclass[dc])
		order.append('all')
		# order the input list by the criteria we just built
		return [t for t in order if t in types]

	def get_recent_events(self, devices, count = 10):
		dev_ids = [dev.device_id for dev in devices]
		# include child devices, e.g. Lutron keypad buttons
		for dev in devices:
			dev_ids.extend(dev.get_child_ids())
		return self.persist.get_recent_events(dev_ids, count)


class StargateGateway(object):
	# gateways should subclass this
	def __init__(self, house, gateway_id):
		assert isinstance(house, StargateHouse)
		assert isinstance(gateway_id, str) or isinstance(gateway_id, unicode)
		self.house = house					# StargateHouse instance
		self.gateway_id = gateway_id		# String, database key (must be unique)

		# Subclass must have:
		# get_device_by_gateway_id(gateway_devid)
		assert callable(self.get_device_by_gateway_id)
