# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of DSC PowerSeries system.
#
# This module provides high-level objects representing the various
# sensors/devices controlled via a DSC PowerSeries alarm and IT-100
# or Envisalink 2DS integration module.
#
# BUGS:
# - reflector is largely untested
# TODO:
# - clean up/flesh out cache; settle on way of doing device ids across zone/partition/other
# - figure out how to model keyfob events
# - split into modules
# - add 'sensor' devclass?
# - persistence, change tracking

import logging
import select
import socket
import threading

import sg_house


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
		self.devclass = 'control'
		self.devtype = 'sensor' # XXX should this be a devclass?
		super(DscZoneSensor, self).__init__(gateway.house, area, gateway, 'zone%d' % zone_number, name)
		self.open_state = None
		self.zone_number = zone_number

	def get_level(self):
		return self.gateway._get_zone_status(self.zone_number)
		
	def get_name_for_level(self, level):
		return 'open' if level else 'closed'

	def is_open(self):
		return self.get_level() == 1
		
	def is_closed(self):
		return not self.is_open()


class CrlfSocketBuffer(object):
	leftovers = ''

	def __init__(self, socket):
		self.socket = socket
	
	def read_lines(self):
		new_data = self.socket.recv(1024)
		data = self.leftovers + new_data
		lines = data.split('\r\n')
		self.leftovers = lines.pop()
		return lines


class ListenerThread(threading.Thread):
	daemon = True
	logger = logging.getLogger(__name__ + '.listener')
	logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

	def __init__(self, gateway):
		super(ListenerThread, self).__init__(name = 'dsc_listener')
		self.gateway = gateway
		self.socket = gateway.socket
		
	def run(self):
		buffer = CrlfSocketBuffer(self.socket)
		while True:
			self.logger.debug('sleep')
			(readable, writable, errored) = select.select([self.socket], [], [self.socket])
			self.logger.debug('wake for input')
			for line in buffer.read_lines():
				self.gateway._receive_dsc_cmd(line)


class ReflectorThread(threading.Thread):
	daemon = True
	logger = logging.getLogger(__name__ + '.reflector')
	logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))
	
	def __init__(self, reflector):
		super(ReflectorThread, self).__init__(name = 'dsc_reflector')
		self.reflector = reflector
		self.listen_socket = reflector.accept_socket
		self.authenticated = False
		
	def run(self):
		# For now, just listen for a single connection. That's all the envisalink does anyway. Really we should
		# allow multiple connections (and garbage collect closed ones).
		# XXX but right now, we don't even listen again if the first one closes.
		self.connected_socket, self.client_address = self.listen_socket.accept()
		logger.info('reflector accepted chained connection from %s' % str(self.client_address))
		self.connected_socket.send('5053CD\r\n') # XXX hardcoded "authentication required" introduction
		s = self.connected_socket
		buffer = CrlfSocketBuffer(s)

		while True:
			(readable, writable, errored) = select.select([s], [], [s])
			assert readable == [s] # XXX only handle one client for now
			for line in buffer.read_lines():
				# XXX we should crack the command, check the checksum, ignore if invalid instead of spamming other clients
				if line[:3] == '005':
					auth_response = self.attempt_auth(line)
					s.send(auth_response + '\r\n')
				elif self.authenticated:
					self.reflector.from_child(line)
				else:
					logger.warning('DSC reflector: child attempted command %s in unauthenticated state' % line[:3])
	
	def attempt_auth(self, line):
		# XXX: should be more careful with state machine, i.e. multiple auth commands. See what real one does and if it matters.
		if line[3:-2] == self.reflector.password: # XXX ignore checksum; we should use a common cmdline cracker and check it
			self.authenticated = True
			logger.info('DSC reflector: child connection authenticated')
			return '5051CB' # XXX hardcoded authentication success response
		else:
			logger.warning('DSC reflector: child connection failed authentication')
			return '5050CA' # XXX hardcoded authentication failure response


class Reflector(object):
	# XXX the envisalink authentication scheme is really lame; we might want to support something
	# better, and/or at least a different password, and/or at least restrict the listening address
	# (assuming that stargate may be running on a box more widely network-accessible than the 2DS
	# itself, for which the only reasonable strategy is to keep it far from the internet).
	def __init__(self, gateway, port, password):
		self.gateway = gateway
		self.port = port
		self.password = password
		
		if self.port:
			self.accept_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.accept_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			self.accept_socket.bind(('', self.port))
			self.accept_socket.listen(1)
			self.reflect_thread = ReflectorThread(self)
			self.send_lock = threading.RLock()
			self.reflect_thread.start()
			
	def to_children(self, cmdline):
		# Cmdline: encoded command with checksum but no CRLF terminator
		if not self.port:
			return
		with self.send_lock:
			if self.reflect_thread.authenticated:
				self.reflect_thread.connected_socket.send(cmdline + '\r\n')
				
	def from_child(self, cmdline):
		# Cmdline: encoded command with checksum but no CRLF terminator
		# Child gave command; pass along to DSC
		assert cmdline[:3] != '005' # make sure children don't mess with parent authentication state
		self.gateway._send_dsc_cmdline(cmdline)


class DscPanelCache(object):
	zone_status = {}
	partition_status = {}
	subscribers = []

	def __init__(self, gateway):
		self.gateway = gateway
		for i in range(1, 65):
			self.zone_status[i] = 'stale'
		for i in range(1, 9):
			self.partition_status[i] = 'stale'
		self.gateway.send_dsc_command(001) # request global status

	def get_zone_status(self, zone_num):
		status = self.zone_status[zone_num]
		while status == 'stale':
			time.sleep(0.1)
			status = self.zone_status[zone_num]
		return status

	# DscGateway private interface
	def _record_zone_status(self, zone_num, status):
		# should be called only by DscGateway._receive_dsc_cmd()
		logger.info('_record_zone_state: zone %d status %d' % (zone_num, status))
		self.zone_status[zone_num] = status
		self._broadcast_change(zone_num, status)

	def _record_partition_status(self, partition_num, status):
		# should be called only by DscGateway._receive_dsc_cmd()
		logger.info('_record_partition_state: partition %d status %d' % (partition_num, status))
		self.partition_status[partition_num] = status
		self._broadcast_change(partition_num, status)

	def _broadcast_change(self, dev_id, state):
		refresh = False # XXX
		logger.debug('broadcast_change: sending on_user_action(dev_id=%s, refresh=%s)' % (dev_id, str(refresh)))
		for subscriber in self.subscribers:
			subscriber.on_user_action(dev_id, state, refresh)


class DscGateway(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, config):
		super(DscGateway, self).__init__(house, gateway_instance_name)
		self._response_cmd_map = {
			501: self._do_invalid_cmd,
			505: self._do_login,
			# zone status updates
			# XXX: note 601-610 all report different things about a zone; should have broader concept of zone state
			609: self._do_zone_open,
			610: self._do_zone_closed,
			# partition status updates
			# XXX: note 650-659 all report different things about a partition; also maybe 66x and 67x. Should have broader concept of partition state
			650: self._do_partition_ready,
			673: self._do_partition_busy,
			840: self._do_partition_trouble_on,
			841: self._do_partition_trouble_off,
			# arm/disarm (DSC terminology is partition open/closing)
			# XXX TODO: 70x (closing), 75x (opening)
			# command in progress
			912: self._do_user_command_invoked,
			# XXX: do I want to consider 660 as part of this or partition status? 912 is more useful as an event notification, assuming it's supported
		}
		# Right now, this only knows how to connect over a TCP socket
		# and authenticate using Envisalink's protocol, so it basically
		# assumes Envisalink. Without too many changes, we could probably
		# talk to a TCP->serial gateway to an IT-100, and without too many
		# more changes, could talk to a serial port connected to an IT-100
		# if one exists. For now, just use weakly-authenticated-TCP.
		self.hostname = config.gateway.hostname
		self.port = 4025
		self.reflector_port = config.gateway.reflector_port if config.gateway.has_key('reflector_port') else 0
		self.password = config.gateway.password
		
		# create devices
		self.panel = DscPanel(self)
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
		self._connect()
		self.listen_thread = ListenerThread(self)
		self.listen_thread.start()
		self.reflector = Reflector(self, self.reflector_port, self.password)

		# and start everything in motion
		self._login(self.password)
		self.cache = DscPanelCache(self)
		
	def _connect(self):
		self.sender_lock = threading.RLock()
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.connect((self.hostname, self.port))
		self.socket.setblocking(0)
		
	def _login(self, password):
		self.send_dsc_command(005, password)

	def send_dsc_command(self, command, data_bytes = []):
		# Can be called on any stargate thread; will send data over network socket to DSC system
		cmdline = self._encode_dsc_command(command, data_bytes)
		self._send_dsc_cmdline(cmdline)
	
	# child-device interface for device status
	def _get_zone_status(self, zone_num):
		return self.cache.get_zone_status(zone_num)

	# private helpers for command send/receive
	def _send_dsc_cmdline(self, cmdline):
		# Cmdline: encoded command with checksum but no CRLF terminator
		# Send over network to panel.
		with self.sender_lock:
			logger.debug('debug: send command: ' + str(cmdline))
			self.socket.send(str(cmdline) + '\r\n')

	def _receive_dsc_cmd(self, cmdline):
		# Called on listener thread when panel says something.
		# Cmdline: encoded command with checksum but no CRLF terminator

		# Parse, and broadcast any interesting event notifications to the SG devices we created
		(cmd_num, cmd_data, checksum) = (int(cmdline[:3]), cmdline[3:-2], cmdline[-2:])
		if cmdline != self._encode_dsc_command(cmd_num, cmd_data):
			logger.warning('response with bad checksum: %s' % cmdline)
			return
		
		logger.debug('dsc panel sent cmd: %s' % cmdline)
		if self._response_cmd_map.has_key(cmd_num):
			self._response_cmd_map[cmd_num](cmd_data)
		else:
			logger.debug('ignoring command %d (no handler)' % cmd_num)

		# pass on to reflector (except for authentication response)
		if cmd_num != 505:
			self.reflector.to_children(cmdline)

	def _encode_dsc_command(self, command, data_bytes):
		# Encode command: 3-digit number as ascii, then any arguments/data
		assert type(command) == int
		cmd_bytes = '%03d' % command
		cmd = []
		checksum = 0
		for byte in cmd_bytes:
			cmd.append(byte)
			checksum += ord(byte)
		for byte in data_bytes:
			cmd.append(byte)
			checksum += ord(byte)
		# add checksum and CRLF terminator
		checksum = checksum % 256
		cmd.extend([hex(nibble)[-1].upper() for nibble in [ checksum / 16, checksum % 16]])
		return ''.join(cmd)
	
	# private handlers for _receive_dsc_cmd
	def _do_invalid_cmd(self, data):
		logger.warning('panel complains of invalid command')

	def _do_login(self, data):
		logger.info('login response: %d' % int(data))
		assert int(data) > 0 # XXX temporary
		# XXX should have a concept of gateway online/offline/error
		
	def _do_zone_open(self, data):
		zone = int(data)
		logger.info('zone %d: open' % zone)
		self.cache._record_zone_status(zone, 1)

	def _do_zone_closed(self, data):
		zone = int(data)
		logger.info('zone %d: closed' % zone)
		self.cache._record_zone_status(zone, 0)

	def _do_partition_ready(self, data):
		partition = int(data)
		logger.info('partition %d: ready' % partition)
		self.cache._record_partition_status(partition, 1)

	def _do_partition_busy(self, data):
		partition = int(data)
		logger.info('partition %d: busy' % partition)
		self.cache._record_partition_status(partition, 0)

	def _do_partition_trouble_on(self, data):
		partition = int(data)
		logger.info('partition %d: TROUBLE' % partition)

	def _do_partition_trouble_off(self, data):
		partition = int(data)
		logger.info('partition %d: no trouble' % partition)

	def _do_user_command_invoked(self, data):
		assert len(data) == 2
		partition_num = int(data[0])
		command_num = int(data[1])
		logger.info('user command %d on partition %d' % (command_num, partition_num))
