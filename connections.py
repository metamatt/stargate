# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides connection-management helpers for gateways with
# long-lived stateful connections.

import logging
import select
import threading


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class CrlfSocketBuffer(object):
	def __init__(self, socket):
		self.socket = socket
		self.leftovers = ''
	
	def read_lines(self):
		new_data = self.socket.recv(1024)
		if len(new_data) == 0:
			raise Exception('read on closed socket')
		data = self.leftovers + new_data
		lines = data.split('\r\n')
		self.leftovers = lines.pop()
		return lines


class ListenerThread(threading.Thread):
	def __init__(self, delegate, name_prefix):
		super(ListenerThread, self).__init__(name = name_prefix + '_listener')
		self.delegate = delegate
		self.daemon = True
		self.logger = logging.getLogger('connectionThreads.' + name_prefix + '_listener')
		self.logger.info('%s: init for listener with level %s' % (self.logger.name, logging.getLevelName(self.logger.level)))
		
	def run(self):
		try:
			sock = self.delegate.socket
			buffer = CrlfSocketBuffer(sock)
			while True:
				self.logger.debug('sleep')
				(readable, writable, errored) = select.select([sock], [], [sock])
				if len(errored):
					raise Exception('socket in error state')
				assert readable == [sock]
				self.logger.debug('wake for input')
				for line in buffer.read_lines():
					self.delegate.receive_from_listener(line)
		except:
			self.logger.exception('listener thread exiting')
			# exit and let watchdog restart us


class SenderThread(threading.Thread):
	def __init__(self, delegate, name_prefix):
		super(SenderThread, self).__init__(name = name_prefix + '_sender')
		self.delegate = delegate
		self.daemon = True
		self.logger = logging.getLogger('connectionThreads.' + name_prefix + '_listener')
		self.logger.info('%s: init for sender with level %s' % (self.logger.name, logging.getLevelName(self.logger.level)))

	def run(self):
		try:
			sock = self.delegate.socket
			while True:
				cmd = self.delegate.send_queue.get()
				self.logger.debug('debug: dequeue and send command: ' + cmd)
				sent = sock.send(cmd + '\r\n')
				if sent != len(cmd) + 2:
					logger.warning('send dequeued command: sent %d of %d bytes' % (sent, 2 + len(cmd)))
				if hasattr(self.delegate, 'separate_sends'):
					self.delegate.separate_sends()
		except:
			self.logger.exception('sender thread exiting')
			# exit and let watchdog restart us


