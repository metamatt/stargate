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
# To do:
# - handle more device types (?)


import json
import logging
import threading
import urllib

from sg_util import AttrDict
import sg_house


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

class VeraDevice(sg_house.StargateDevice):
	devclass = 'output'

	def __init__(self, gateway, dev_sdata):
		self.vera_room = gateway.rooms[dev_sdata.room]
		self.vera_id = dev_sdata.id
		super(VeraDevice, self).__init__(gateway.house, self.vera_room.sg_area, gateway, str(self.vera_id), dev_sdata.name)

	def is_pending(self):
		# Determine whether Vera has any active jobs for this device.
		# XXX may want to have some concept of the jobs we started, not just all jobs for the device.
		return self.vera_id in self.gateway._vera_devices_with_jobs_in_progress()
	

class VeraDoorLock(VeraDevice):
	devtype = 'doorlock'
	possible_states = ( 'pending', 'unlocked', 'locked' )
	service_id = 'urn:micasaverde-com:serviceId:DoorLock1'
	lock_state_var = 'Status'

	def __init__(self, gateway, dev_sdata):
		super(VeraDoorLock, self).__init__(gateway, dev_sdata)
		self.level_step = self.level_max = 1
		self.last_locked_state = int(dev_sdata.locked)
		self.house.events.on_device_state_change(self, synthetic = True)

	def is_locked(self):
		return self.get_level() == 1
		
	def is_unlocked(self):
		return not self.is_locked()
		
	def be_locked(self):
		self.set_level(1)
	
	def be_unlocked(self):
		self.set_level(0)
		
	def get_level(self):
		return self.gateway._luup_get_variable(VeraDoorLock.service_id, self.vera_id, VeraDoorLock.lock_state_var)
		
	def set_level(self, level):
		target = 1 if level else 0
		self.gateway._luup_set_variable_target(VeraDoorLock.service_id, self.vera_id, VeraDoorLock.lock_state_var, target)
		
	def get_name_for_level(self, level):
		return 'locked' if level else 'unlocked'
		
	def vera_poll_update(self, dev_sdata):
		locked = int(dev_sdata.locked)
		logger.debug('device %s state last %d now %d' % (self.name, self.last_locked_state, locked))
		if locked != self.last_locked_state:
			self.last_locked_state = locked
			self.house.events.on_device_state_change(self)


class VeraRoom(object):
	def __init__(self, gateway, vera_room):
		self.gateway = gateway
		self.vera_room = vera_room
		# match with house area
		self.sg_area = gateway.house.get_area_by_name(vera_room.name)


class VeraGateway(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, hostname, poll_interval):
		super(VeraGateway, self).__init__(house, gateway_instance_name)
		self.hostname = hostname
		self.port = 3480
		self.poll_interval = poll_interval
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
			
		# create poll thread to periodically poll Vera for changes
		self._install_periodic_poller()

	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		# XXX this is uncalled, and probably would get strings instead of ints
		assert isinstance(gateway_devid, int)
		vera_id = int(gateway_devid)
		return self.devices[vera_id]
		
	# private helper for device creation
	def _create_device(self, dev_sdata):
		# map for correct VeraDevice subclass matching Vera device type.
		map_sdata_device_name_to_class = {
			u'Door lock': VeraDoorLock,
			# no more for now -- the only examples I have are camera/alarm/sensor and those
			# are not interesting via Vera; if I want to talk to them I'll do it directly
		}

		try:
			cls = map_sdata_device_name_to_class[self.catmap[dev_sdata.category].name]
		except KeyError:
			category = self.catmap[dev_sdata.category] if self.catmap.has_key(dev_sdata.category) else ('#%d' % dev_sdata.category)
			logger.info('Ignoring Vera device "%s" of unknown type "%s"' % (dev_sdata.name, category))
			return None
		return cls(self, dev_sdata)

	# private helper for change-poll-notification
	def _install_periodic_poller(self):
		def poll_callback(self):
			# read sdata and re-forward every device its current data record
			try:
				sdata = self._vera_luup_request('sdata')
				for device in sdata.devices:
					if self.devices.has_key(device.id) and self.devices[device.id]:
						self.devices[device.id].vera_poll_update(device)
			except Exception as ex:
				logger.exception(ex)
			# and reinstall this one-shot timer
			self._install_periodic_poller()
		self._poll_thread = threading.Timer(self.poll_interval, poll_callback, args = [self])
		self._poll_thread.setDaemon(True)
		self._poll_thread.setName('vera_poll_timer')
		self._poll_thread.start()

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
	
