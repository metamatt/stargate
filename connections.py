# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides connection-management helpers for gateways with
# long-lived stateful connections.

import logging
import select
import socket
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
			raise Exception('read on socket failed; assuming other end closed')
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
			# close socket so watchdog notices; exit and let watchdog restart us
			sock.close()


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
			# close socket so watchdog notices; exit and let watchdog restart us
			sock.close()


class CleanupAndRestart(threading.Thread):
	def __init__(self, handler):
		super(CleanupAndRestart, self).__init__(name = 'conn_reconnect')
		self.daemon = True
		(self.threads, self.reconnect) = handler

	def run(self):
		logger.warn('watched socket closed; waiting for %d threads' % len(self.threads))
		for t in self.threads:
			# XXX horrible hack to force instances of SenderThread to exit
			if isinstance(t, SenderThread):
				logger.debug('sending SenderThread null request to force wakeup')
				t.delegate.send_queue.put('')
			t.join()
		logger.warn('threads exited; invoking reconnect handler')
		self.reconnect()
		logger.warn('reconnect complete')


class SgWatchdog(threading.Thread):
	def __init__(self):
		super(SgWatchdog, self).__init__(name = 'conn_watcher')
		self.daemon = True
		self.watches = {}

	def add(self, threads, socket, reconnect):
		# XXX we should have a lock around changing/reading the watches map
		self.watches[socket] = (threads, reconnect)
		# XXX poke self to redo run loop noticing new add

	def detect_bad_sockets(self):
		closed = []
		for fd in self.watches.keys():
			try:
				select.select([], [], [fd], 0)
				logger.debug('fd %s (%d) is ok' % (fd, fd.fileno()))
			except socket.error as se:
				if se[0] == socket.EBADF:
					logger.debug('fd %s got EBADF; pruning' % fd)
					closed.append(fd)
				continue
			except:
				logger.exception('unexpected other problem probing for closed fd')
		return closed

	def run(self):
		while True:
			try:
				# if any watched socket closes, wait for associated threads to die, and invoke reconnect
				# XXX passing a bad fd to select results in socket library throwing a EBADF exception. So how do I tell which socket did that?
				logger.debug('sleep')
				(readable, writable, errored) = select.select([], [], self.watches.keys(), 1) # XXX timeout to detect adds, should be event-based
				logger.debug('wake: count r/w/e = %d/%d/%d' % (len(readable), len(writable), len(errored)))
				logger.debug('invoking %d cleanups' % len(errored))
				for bad in errored:
					CleanupAndRestart(self.watches.pop(bad)).start()
				logger.debug('done with cleanup; repeat')
			except socket.error as se:
				if se[0] == socket.EBADF:
					errored = self.detect_bad_sockets()
					logger.debug('invoking %d cleanups' % len(errored))
					for bad in errored:
						CleanupAndRestart(self.watches.pop(bad)).start()
					continue
			except:
				logger.exception('exception in watchdog thread')
