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
# - in-progress state awareness
# - polling/notification for device history tracking
# - other device types (?)


import json
import logging
import urllib

import sg_house


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

class VeraDevice(sg_house.StargateDevice):
	def __init__(self, house, area, gateway, vera_id, name):
		self.devclass = 'output'
		super(VeraDevice, self).__init__(house, area, gateway, str(vera_id), name)
		self.vera_id = vera_id
		self.gateway._register_device(self)

	def is_pending(self):
		# Determine whether Vera has any active jobs for this device.
		# XXX may want to have some concept of the jobs we started, not just all jobs for the device.
		return self.vera_id in self.gateway._vera_devices_with_jobs_in_progress()
	

class VeraDoorLock(VeraDevice):
	KNOWN_STATES_IN_ORDER = [ 'pending', 'unlocked', 'locked' ]
	service_id = 'urn:micasaverde-com:serviceId:DoorLock1'
	lock_state_var = 'Status'

	def __init__(self, house, area, gateway, vera_id, name):
		super(VeraDoorLock, self).__init__(house, area, gateway, vera_id, name)
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
	def __init__(self, house, gateway_instance_name, hostname, devices):
		super(VeraGateway, self).__init__(house, gateway_instance_name)
		self.hostname = hostname
		self.port = 49451
		self.devices = {}

		# fake global 'vera' area for now
		self.area = house.get_area_by_name('Vera devices')

		# build devices mentioned in config file
		for dev_id in devices:
			VeraDoorLock(house, self.area, self, dev_id, devices[dev_id])
		
		# OK, tools at my disposal:
		# room enumeration: sdata or user_data
		# device enumeration with name and type: sdata or user_data
		# check status: get_variable or sdata or user_data
		# set status: action
		# notify of change: unknown, poll get_variable or sdata?
		# sdata seems like the way to go, but it uses funny (simplified) device types: locks have 'locked' field and a 'category' field that maps through a separate table to 'Door lock'.
		# get_variable and action need 'serviceId=urn:micasaverde-com:serviceId:DoorLock1&Variable=Status', which is better visible in user_data.
		# but user_data is a PITA, I really don't want to parse all that, so I might as well just hardcode the serviceId and variable info for the device types I care about.
		# Which is only doorlock, since alarm stuff (sensor/panel/partition) is better handled direct (I need 912 codes); I have no plans for camera; I have no other devices to test.

	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		assert isinstance(gateway_devid, int)
		vera_id = int(gateway_devid)
		return self.devices[vera_id]

	# private interface for owned objects to populate node tree
	def _register_device(self, device):
		self.devices[device.vera_id] = device
		
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
	
