# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of DSC PowerSeries system.
#
# This module provides high-level objects representing the various
# sensors/devices controlled via a DSC PowerSeries alarm and IT-100
# or Envisalink 2DS integration module.
#
# TODO:
# - figure out how to model keyfob events
# - persistence, change tracking

import logging

import sg_house
from dsc_panel import DscPanelServer
from dsc_reflector import Reflector


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class DscPanel(sg_house.StargateDevice):
	KNOWN_STATES_IN_ORDER = [ 'placeholder' ]

	def __init__(self, gateway):
		self.devclass = 'control' # XXX: is it? compound/parent might be better, with a bunch of outputs and controls underneath.
		self.devtype = 'placeholder'
		area = gateway.house # XXX for now
		super(DscPanel, self).__init__(gateway.house, area, gateway, 'panel', 'DSC PowerSeries')

	# as control: read of events mapped to keyfob buttons, but what object do those land on?


class DscPartition(sg_house.StargateDevice):
	KNOWN_STATES_IN_ORDER = [ 'ready', 'trouble', 'armed' ]

	def __init__(self, gateway, partition_num, name):
		self.devclass = 'control'
		self.devtype = 'alarmpartition'
		area = gateway.house # XXX for now
		super(DscPartition, self).__init__(gateway.house, area, gateway, 'partition%d' % partition_num, name)

	# as a control: this should be able to arm/disarm (read and write)


class DscZoneSensor(sg_house.StargateDevice):
	KNOWN_STATES_IN_ORDER = [ 'closed', 'open' ]

	def __init__(self, gateway, area, zone_number, name):
		self.devclass = 'sensor'
		self.devtype = 'closure'
		super(DscZoneSensor, self).__init__(gateway.house, area, gateway, 'zone%d' % zone_number, name)
		self.open_state = None
		self.zone_number = zone_number

	def get_level(self):
		return self.gateway.get_zone_status(self.zone_number)
		
	def get_name_for_level(self, level):
		return 'open' if level else 'closed'

	def is_open(self):
		return self.get_level() == 1
		
	def is_closed(self):
		return not self.is_open()


class DscGateway(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, config):
		super(DscGateway, self).__init__(house, gateway_instance_name)
		
		# create devices
		self.panel_device = DscPanel(self)
		# parse layout from config file
		# areas
		areas_by_zone = {}
		for area_name in config.area_mapping: # map name: list of zone ids
			sg_area = house.get_area_by_name(area_name)
			for zone_num in config.area_mapping[area_name]:
				areas_by_zone[zone_num] = sg_area
		# zones
		self.zones_by_id = {}
		for zone_num in config.zone_names:
			self.zones_by_id[zone_num] = DscZoneSensor(self, areas_by_zone[zone_num], zone_num, config.zone_names[zone_num])
		# partitions
		self.partitions_by_id = {}
		for partition_num in config.partition_names:
			self.partitions_by_id[partition_num] = DscPartition(self, partition_num, config.partition_names[partition_num])

		# set up network connections
		self.panel_server = DscPanelServer(self, config.gateway.hostname, 4025, config.gateway.password)
		if config.gateway.has_key('reflector_port'):
			self.reflector = Reflector(self, config.gateway.reflector_port, config.gateway.password)
		else:
			self.reflector = None

		# and start everything in motion
		self.panel_server.connect()

	# child-device interface for device status
	def get_zone_status(self, zone_num):
		return self.panel_server.cache.get_zone_status(zone_num)
