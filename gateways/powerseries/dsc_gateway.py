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
	devclass = 'control' # XXX: is it? compound/parent might be better, with a bunch of outputs and controls underneath.
	devtype = 'repeater' # XXX
	possible_states = ()

	def __init__(self, gateway):
		area = gateway.house # XXX for now
		super(DscPanel, self).__init__(gateway.house, area, gateway, 'panel', 'DSC PowerSeries')

	# as control: read of events mapped to keyfob buttons, but what object do those land on?


class DscPartition(sg_house.StargateDevice):
	devclass = 'control'
	devtype = 'alarmpartition'
	possible_states = ( 'ready', 'trouble', 'armed' )

	def __init__(self, gateway, partition_num, name):
		area = gateway.house # XXX for now
		super(DscPartition, self).__init__(gateway.house, area, gateway, 'partition:%d' % partition_num, name)

	# as a control: this should be able to arm/disarm (read and write)


class DscZoneSensor(sg_house.StargateDevice):
	devclass = 'sensor'
	devtype = 'closure'
	possible_states = ( 'closed', 'open' )

	def __init__(self, gateway, area, zone_number, name):
		super(DscZoneSensor, self).__init__(gateway.house, area, gateway, 'zone:%d' % zone_number, name)
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

	def on_user_action(self, level, synthetic):
		self.house.events.on_device_state_change(self, synthetic) # state


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
		self.panel_server.connect(self)

	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		# our devid format is "scope,num" where scope is one of: [ zone, partition, command ].
		(scope, num) = self.crack_dsc_devid(gateway_devid)
		if scope == 'zone':
			return self.zones_by_id[num]
		elif scope == 'partition':
			return self.partitions_by_id[num]
		else:
			raise Error('whoops')

	def crack_dsc_devid(self, gateway_devid):
		cracked = gateway_devid.split(':')
		assert len(cracked) == 2
		assert int(cracked[1]) > 0
		return (cracked[0], int(cracked[1]))
		
	# child-device interface for device status
	def get_zone_status(self, zone_num):
		return self.panel_server.cache.get_zone_status(zone_num)

	def send_user_command(self, partition_num, user_cmd_num):
		# Envisalink UI calls this "PGM", but it's really the user-command which you often map PGM outputs to listen to, but it's not actually that direct.
		# partition_num is 1..8
		# user_cmd_num is 1..4
		command = 20 # 020 in DSC-speak, but Python interprets that as octal, which is not what we want
		data = [ str(partition_num), str(user_cmd_num) ]
		assert len(data) == 2
		self.panel_server.send_dsc_command(command, data)

	# panel action callback
	def on_user_action(self, zone_id, state, refresh):
		logger.debug('panel action zone %d' % zone_id)
		if self.zones_by_id.has_key(zone_id):
			device = self.zones_by_id[zone_id] # XXX should handle other event sources: partition, command-output
			device.on_user_action(state, refresh)
