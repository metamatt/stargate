# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of MiCasaVerde Vera system.
#
# This module provides high-level objects representing the various
# Vera devices.
#
# Most useful Vera programming reference docs:
# http://wiki.micasaverde.com/index.php/Luup_Protocol
# http://wiki.micasaverde.com/index.php/Luup_Sdata
# http://wiki.micasaverde.com/index.php/Luup_Requests
#
# XXX to-do:
# - device enumeration / room assignment
# - polling/notification for device history tracking
# - other device types (?)


import json
import logging
import urllib

import sg_house


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

class VeraDevice(sg_house.StargateDevice):
	def __init__(self, vera_room, vera_id, name):
		self.devclass = 'output'
		self.vera_room = vera_room
		self.vera_id = vera_id
		super(VeraDevice, self).__init__(vera_room.gateway.house, vera_room.sg_area, vera_room.gateway, str(vera_id), name)

	def is_pending(self):
		# Determine whether Vera has any active jobs for this device.
		# XXX may want to have some concept of the jobs we started, not just all jobs for the device.
		return self.vera_id in self.gateway._vera_devices_with_jobs_in_progress()
	

class VeraDoorLock(VeraDevice):
	KNOWN_STATES_IN_ORDER = [ 'pending', 'unlocked', 'locked' ]
	service_id = 'urn:micasaverde-com:serviceId:DoorLock1'
	lock_state_var = 'Status'

	def __init__(self, vera_room, vera_id, name):
		super(VeraDoorLock, self).__init__(vera_room, vera_id, name)
		self.devtype = 'doorlock'
		self.level_step = self.level_max = 1

	def is_locked(self):
		return self.get_level() == 1
		
	def is_unlocked(self):
		return not self.is_locked()
		
	def be_locked(self):
		self.set_level(1)
	
	def be_unlocked(self):
		self.set_level(0)
		
	def get_level(self):
		return self.gateway._luup_get_variable(self.service_id, self.vera_id, self.lock_state_var)
		
	def set_level(self, level):
		target = 1 if level else 0
		self.gateway._luup_set_variable_target(self.service_id, self.vera_id, self.lock_state_var, target)
		
	def get_name_for_level(self, level):
		return 'locked' if level else 'unlocked'


class VeraRoom(object):
	gateway = None
	sg_area = None
	vera_room = None
	
	def __init__(self, gateway, vera_room):
		self.gateway = gateway
		self.vera_room = vera_room
		# match with house area
		self.sg_area = gateway.house.get_area_by_name(vera_room.name)


# Simple class to allow attribute-style lookup of dictionary members.
class AttrDict(dict):
	# This handles only get, not set or del. I make no representation that
	# it works for all possible cases; just that it works well enough for
	# the use here (wrapping read-only dictionary we read from json).
	
	# Note that we automatically convert embedded dictionaries to AttrDicts,
	# and embedded lists of dictionaries to lists of AttrDicts, on extraction
	# (as long as you use our method of extraction).
	def __getitem__(self, name):
		item = super(AttrDict, self).__getitem__(name)
		if type(item) == dict:
			return AttrDict(item)
		elif type(item) == list:
			return [AttrDict(i) for i in item]
		else:
			return item
	__getattr__ = __getitem__


class VeraGateway(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, hostname):
		super(VeraGateway, self).__init__(house, gateway_instance_name)
		self.hostname = hostname
		self.port = 49451
		self.devices = {} # map from int id to VeraDevice
		self.rooms = {} # map from int id to VeraRoom
		self.catmap = {} # map from int id to AttrDict representing sdata category response
		
		# parse sdata to enumerate rooms and devices
		# XXX ignore "sections"
		sdata = self._vera_luup_request('sdata')
		for room in sdata.rooms:
			self.rooms[room.id] = VeraRoom(self, room)
		for category in sdata.categories:
			self.catmap[category.id] = category
		for device in sdata.devices:
			self.devices[device.id] = self._create_device(device)

	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		assert isinstance(gateway_devid, int)
		vera_id = int(gateway_devid)
		return self.devices[vera_id]
		
	# private helper for device creation
	def _create_device(self, sdata_device):
		# map for correct VeraDevice subclass matching Vera device type.
		map_sdata_device_name_to_class = {
			u'Door lock': VeraDoorLock,
			# no more for now -- the only examples I have are camera/alarm/sensor and those
			# are not interesting via Vera; if I want to talk to them I'll do it directly
		}

		try:
			cls = map_sdata_device_name_to_class[self.catmap[sdata_device.category].name]
		except KeyError:
			category = self.catmap[sdata_device.category] if self.catmap.has_key(sdata_device.category) else ('#%d' % sdata_device.category)
			logger.error('unknown vera device category %s for device %s' % (category, sdata_device.name))
			return None
		return cls(self.rooms[sdata_device.room], sdata_device.id, sdata_device.name)
	

	# private interface for owned objects to talk to vera gateway
	def _luup_get_variable(self, service_id, device_num, variable_name):
		device_variable_triad = self._device_variable_triad(device_num, service_id, variable_name)
		return self._vera_luup_request('variableget', device_variable_triad)
		
	def _luup_set_variable_target(self, service_id, device_num, variable_name, target_value):
		# XXX note that there's a direct 'setvariable' command which changes the variable value without causing associated physical actions; don't use it.
		# We need to use the 'action' command with SetTarget verb.
		action_details = 'action=SetTarget&newTargetValue=%d' % target_value
		return self._luup_action(service_id, device_num, variable_name, action_details)
	
	def _luup_action(self, service_id, device_num, variable_name, action_details):
		device_variable_triad = self._device_variable_triad(device_num, service_id, variable_name)
		args = '%s&%s' % (device_variable_triad, action_details);
		return self._vera_luup_request('action', args)
	
	def _vera_devices_with_jobs_in_progress(self):
		status = self._vera_luup_request('status')
		return [dev.id for dev in status.devices if len(dev.Jobs)]
		
	@staticmethod
	def _device_variable_triad(device_num, service_id, variable_name):
		return 'DeviceNum=%d&serviceId=%s&Variable=%s' % (device_num, service_id, variable_name)
	
	def _vera_luup_request(self, luup_cmd, *args):
		url = 'http://%s:%d/data_request?id=%s&output_format=json' % (self.hostname, self.port, luup_cmd)
		if len(args):
			arg_string = '&'.join(args)
			url += '&' + arg_string
		logger.debug('vera command: %s' % url)
		stream = urllib.urlopen(url)
		response = json.load(stream)
		return AttrDict(response) if type(response) == dict else response
	
