# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of MiCasaVerde Vera system.
#
# This module provides high-level objects representing the various
# Vera devices.


import logging

import sg_house


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

class VeraDevice(sg_house.StargateDevice):
	KNOWN_STATES_IN_ORDER = [ 'unlocked', 'locked' ]

	def __init__(self, house, area, gateway, vera_id, name):
		super(VeraDevice, self).__init__(house, area, gateway, str(vera_id), name)
		self.devclass = 'output' # XXX: for now
		self.devtype = 'deadbolt'
		self.level_step = 100
		self.vera_id = vera_id
		self.gateway._register_device(self)

	def is_locked(self):
		return self.get_level() == 1
		
	def is_unlocked(self):
		return not self.is_locked()
	
	def be_locked(self):
		self.set_level(1)
	
	def be_unlocked(self):
		self.set_level(0)
		
	def get_level(self):
		return 0 # XXX
		
	def set_level(self):
		pass # XXX
		
	def get_name_for_level(self, level):
		return 'locked' if level else 'unlocked'


class VeraGateway(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, hostname, devices):
		super(VeraGateway, self).__init__(house, gateway_instance_name)
		self.hostname = hostname
		self.devices = {}

		# fake global 'vera' area for now
		self.area = house.get_area_by_name('Vera devices')

		# build devices mentioned in config file
		for dev_id in devices:
			VeraDevice(house, self.area, self, dev_id, devices[dev_id])

	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		assert isinstance(gateway_devid, int)
		vera_id = int(gateway_devid)
		return self.devices[vera_id]

	# private interface for owned objects to populate node tree
	def _register_device(self, device):
		self.devices[device.vera_id] = device
