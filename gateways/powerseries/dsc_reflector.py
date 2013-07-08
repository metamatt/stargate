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

import connections
import logging
import select
import socket
import threading


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class ReflectorThread(threading.Thread):
	def __init__(self, parent, socket, client_address):
		super(ReflectorThread, self).__init__(name = 'dsc_reflector')
		self.daemon = True
		self.parent = parent
		self.reflector = parent.reflector
		self.connected_socket = socket
		self.client_address = client_address
		self.authenticated = False

	def run(self):
		self.connected_socket.send('5053CD\r\n') # XXX hardcoded "authentication required" introduction
		s = self.connected_socket
		buffer = connections.CrlfSocketBuffer(s)

		try:
			while True:
				(readable, writable, errored) = select.select([s], [], [s])
				if errored:
					logger.warning('reflector child reported error in select()')
					break
				assert readable == [s]
				for line in buffer.read_lines():
					# XXX we should crack the command, check the checksum, ignore if invalid instead of spamming other clients
					if line[:3] == '005':
						auth_response = self.attempt_auth(line)
						s.send(auth_response + '\r\n')
					elif self.authenticated:
						self.reflector.from_child(line)
					else:
						logger.warning('DSC reflector: child attempted command %s in unauthenticated state' % line[:3])
		except:
			logger.exception('error in reflector child')

		self.parent.child_exit(self)
	
	def attempt_auth(self, line):
		# XXX: should be more careful with state machine, i.e. multiple auth commands. See what real one does and if it matters.
		if line[3:-2] == self.reflector.password: # XXX ignore checksum; we should use a common cmdline cracker and check it
			self.authenticated = True
			logger.info('DSC reflector: child connection authenticated')
			return '5051CB' # XXX hardcoded authentication success response
		else:
			logger.warning('DSC reflector: child connection failed authentication')
			return '5050CA' # XXX hardcoded authentication failure response


class ReflectorParentThread(threading.Thread):
	def __init__(self, reflector):
		super(ReflectorParentThread, self).__init__(name = 'dsc_reflector_listen')
		self.daemon = True
		self.reflector = reflector
		self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.listen_socket.bind(('', self.reflector.port))
		self.listen_socket.listen(1)
		self.children = []

	def run(self):
		# Listen for connections, and handle them in new threads
		while True:
			connected_socket, client_address = self.listen_socket.accept()
			logger.info('reflector accepted chained connection from %s' % str(client_address))
			child = ReflectorThread(self, connected_socket, client_address)
			self.children.append(child)
			child.run()

	def to_children(self, cmdLine):
		logger.debug('send to %d children: %s' % (len(self.children), cmdLine))
		for child in self.children:
			logger.debug('to child %s' % str(child.client_address))
			if child.authenticated:
				try:
					child.connected_socket.send(cmdLine + '\r\n')
				except:
					logger.exception('unable to send to child %s' % str(child.client_address))

	def child_exit(self, child):
		logger.info('reflector lost chained connection to %s' % str(child.client_address))
		self.children.remove(child)


class Reflector(object):
	# XXX the envisalink authentication scheme is really lame; we might want to support something
	# better, and/or at least a different password, and/or at least restrict the listening address
	# (assuming that stargate may be running on a box more widely network-accessible than the 2DS
	# itself, for which the only reasonable strategy is to keep it far from the internet).
	def __init__(self, gateway, port, password):
		self.gateway = gateway
		self.port = port
		self.password = password
		self.reflect_thread = None
		
		if self.port:
			self.reflect_thread = ReflectorParentThread(self)
			self.send_lock = threading.RLock()
			self.reflect_thread.start()
			
	def to_children(self, cmdline):
		if self.reflect_thread:
			with self.send_lock:
				self.reflect_thread.to_children(cmdline)
				
	def from_child(self, cmdline):
		# Child gave command; pass along to DSC
		if cmdline[:3] == '005': # make sure children don't mess with parent authentication state
			return
		self.gateway.panel_server._send_dsc_cmdline(cmdline)
