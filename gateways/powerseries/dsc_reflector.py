# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of DSC PowerSeries system.
#
# This module handles providing additional TCP connections to the DSC panel's integration
# interface, by chaining through the one we control (since the Envisalink 2DS allows only
# one client at a time).
#
# Terminology note: 'cmdline' variable holds encoded command with checksum but no CRLF terminator
#
# BUGS:
# - reflector is largely untested

import logging
import socket
import threading

logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class ReflectorThread(threading.Thread):
	daemon = True
	
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
		if not self.port:
			return
		with self.send_lock:
			if self.reflect_thread.authenticated:
				self.reflect_thread.connected_socket.send(cmdline + '\r\n')
				
	def from_child(self, cmdline):
		# Child gave command; pass along to DSC
		assert cmdline[:3] != '005' # make sure children don't mess with parent authentication state
		self.gateway.panel_server._send_dsc_cmdline(cmdline)
