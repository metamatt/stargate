# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of DSC PowerSeries system.
#
# This module handles the TCP connection to the panel's integration interface,
# and listens to it in monitor mode to build a cache of device state for the
# entire system. It provides a low-level interface for querying zone/partition
# state and invoking actions.
#
# Terminology note: 'cmdline' variable holds encoded command with checksum but no CRLF terminator
#
# TODO:
# - clean up/flesh out cache; settle on way of doing device ids across zone/partition/other

import logging
import select
import socket
import threading


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class DscPanelCache(object):
	zone_status = {}
	partition_status = {}
	subscribers = []

	def __init__(self, panel_server):
		self.panel_server = panel_server
		for i in range(1, 65):
			self.zone_status[i] = 'stale'
		for i in range(1, 9):
			self.partition_status[i] = 'stale'
		self.panel_server.send_dsc_command(001) # request global status

	def get_zone_status(self, zone_num):
		status = self.zone_status[zone_num]
		while status == 'stale':
			time.sleep(0.1)
			status = self.zone_status[zone_num]
		return status

	# DscGateway private interface
	def _record_zone_status(self, zone_num, status):
		# should be called only by DscPanelServer._receive_dsc_cmd()
		logger.info('_record_zone_state: zone %d status %d' % (zone_num, status))
		self.zone_status[zone_num] = status
		self._broadcast_change(zone_num, status)

	def _record_partition_status(self, partition_num, status):
		# should be called only by DscPanelServer._receive_dsc_cmd()
		logger.info('_record_partition_state: partition %d status %d' % (partition_num, status))
		self.partition_status[partition_num] = status
		self._broadcast_change(partition_num, status)

	def _broadcast_change(self, dev_id, state):
		refresh = False # XXX
		logger.debug('broadcast_change: sending on_user_action(dev_id=%s, refresh=%s)' % (dev_id, str(refresh)))
		for subscriber in self.subscribers:
			subscriber.on_user_action(dev_id, state, refresh)


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


class DscPanelServer(object):
	def __init__(self, gateway, hostname, port, password):
		self.gateway = gateway
		self.hostname = hostname
		self.port = port
		self.password = password

	def connect(self):
		# Right now, this only knows how to connect over a TCP socket
		# and authenticate using Envisalink's protocol, so it basically
		# assumes Envisalink. Without too many changes, we could probably
		# talk to a TCP->serial gateway to an IT-100, and without too many
		# more changes, could talk to a serial port connected to an IT-100
		# if one exists. For now, just use weakly-authenticated-TCP.
		self.sender_lock = threading.RLock()
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.connect((self.hostname, self.port))
		self.socket.setblocking(0)
		self.listen_thread = ListenerThread(self)
		self.listen_thread.start()
		# log in
		self.send_dsc_command(005, self.password)
		# cache creation will issue the global-status command triggering many responses
		self.cache = DscPanelCache(self)

	def send_dsc_command(self, command, data_bytes = []):
		# Can be called on any stargate thread; will send data over network socket to DSC system
		cmdline = self._encode_dsc_command(command, data_bytes)
		self._send_dsc_cmdline(cmdline)
	
	# private helpers for command send/receive
	def _send_dsc_cmdline(self, cmdline):
		# Send over network to panel.
		with self.sender_lock:
			logger.debug('debug: send command: ' + str(cmdline))
			self.socket.send(str(cmdline) + '\r\n')

	def _receive_dsc_cmd(self, cmdline):
		# Called on listener thread when panel says something.

		# Parse, and broadcast any interesting event notifications to the SG devices we created
		(cmd_num, cmd_data, checksum) = (int(cmdline[:3]), cmdline[3:-2], cmdline[-2:])
		if cmdline != self._encode_dsc_command(cmd_num, cmd_data):
			logger.warning('response with bad checksum: %s' % cmdline)
			return
		
		logger.debug('dsc panel sent cmd: %s' % cmdline)
		if self._response_cmd_map.has_key(cmd_num):
			self._response_cmd_map[cmd_num](self, cmd_data)
		else:
			logger.debug('ignoring command %d (no handler)' % cmd_num)

		# pass on to reflector (except for authentication response)
		if self.gateway.reflector and cmd_num != 505:
			self.gateway.reflector.to_children(cmdline)

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

	_response_cmd_map = {
		501: _do_invalid_cmd,
		505: _do_login,
		# zone status updates
		# XXX: note 601-610 all report different things about a zone; should have broader concept of zone state
		609: _do_zone_open,
		610: _do_zone_closed,
		# partition status updates
		# XXX: note 650-659 all report different things about a partition; also maybe 66x and 67x. Should have broader concept of partition state
		650: _do_partition_ready,
		673: _do_partition_busy,
		840: _do_partition_trouble_on,
		841: _do_partition_trouble_off,
		# arm/disarm (DSC terminology is partition open/closing)
		# XXX TODO: 70x (closing), 75x (opening)
		# command in progress
		912: _do_user_command_invoked,
		# XXX: do I want to consider 660 as part of this or partition status? 912 is more useful as an event notification, assuming it's supported
	}
