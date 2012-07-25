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

# A note on object instantiation:
# - toplevel framework instantiates a single StargateHouse instance
# - StargateHouse instantiates gateway plugins (StargateGateway instances)
# - each gateway plugin creates 0 or more device instances, which are StargateDevice subclasses
# - the gateway plugin is responsible for mapping the device instances it creates to StargateArea instances
#   (existing, or created on the fly) by asking the house to do so
# - thus, StargateHouse creates StargateArea instances during gateway initialization


class StargateDevice(object):
	# Devices are subclassed into gateway-specific device classes, and created by the gateways.
	# Devices automatically register with their area upon creation. The owning gateway should
	# also be able to look them up.
	
	# XXX: provide some idea of common type/capability information?
	
	# predefined fields that all devices must have, all subclasses must fill in
	house = None            # StargateHouse instance
	area = None             # StargateArea instance, where this device lives
	gateway = None          # StargateGateway instance, the gateway module managing this device
	gw_rel_id = None        # String, the id for this device (unique and meaningful only per gateway)
	name = None             # String, human-readable name
	
	def __init__(self, house, area, gateway, gw_rel_id, name):
		assert isinstance(house, StargateHouse)
		assert isinstance(area, StargateArea)
		assert isinstance(gateway, StargateGateway)
		assert isinstance(gw_rel_id, str) or isinstance(gw_rel_id, unicode)
		assert isinstance(name, str) or isinstance(name, unicode)
		self.house = house
		self.area = area
		self.gateway = gateway
		self.gw_rel_id = gw_rel_id
		self.name = name
		
		self.area.register_device(self)


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
		self.areas = {}

	def register_device(self, device):
		self.devices.append(device)
	

class StargateHouse(StargateArea):
	persist = None          # SgPersistence instance
	gateways = None         # Map from gateway name to gateway object
	areas = None            # Map from area name to area object

	def __init__(self, config):
		self.house = self
		super(StargateHouse, self).__init__(self, config['house_name'])
		self.persist = persistence.SgPersistence('stargate.sqlite')
		self.gateways = gateways.load_all(self, config['gateways'])
	
	def get_device_by_gateway_and_id(self, gateway_id, gw_rel_id):
		gateway = self.gateways[gateway_id]
		return gateway.get_device_by_gateway_id(gw_rel_id)
	
	def get_area_by_name(self, area_name):
		# XXX currently always creates children of the root area
		if not self.areas.has_key(area_name):
			self.areas[area_name] = StargateArea(self, area_name)
		return self.areas[area_name]

	# XXX needs unification with new framework
	# UI needs to start using stargate gateway:gw_rel ids, not lutron iids
	def get_device_type_state_map(self, devclass = 'device'):
		return self.gateways['radiora2'].root_area.get_device_type_state_map(devclass)
	def get_areas_filtered_by(self, filters):
		return self.gateways['radiora2'].root_area.get_areas_filtered_by(filters)
	def get_devices_filtered_by(self, filters = [], devclass = 'device'):
		return self.gateways['radiora2'].root_area.get_devices_filtered_by(filters, devclass)
	def get_devicearea_by_iid(self, iid):
		return self.gateways['radiora2'].get_devicearea_by_iid(iid)
	def get_device_by_iid(self, iid):
		return self.gateways['radiora2']._get_device_by_iid(iid)
	@staticmethod
	def get_supported_actions(devices):
		return reduce(set.intersection, map(lambda dev: dev.get_possible_actions(), devices))


class StargateGateway(object):
	# gateways should subclass this
	house = None         # StargateHouse instance
	name = None          # String, human-readable name
	
	def __init__(self, house, name):
		assert isinstance(house, StargateHouse)
		assert isinstance(name, str) or isinstance(name, unicode)
		self.house = house
		self.name = name
