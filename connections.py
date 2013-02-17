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
		# XXX I haven't tested what happens if reconnect tries to connect too early, say to
		# a hardware device that disconnected because it rebooted and isn't back up yet.
		self.reconnect()
		logger.warn('reconnect complete')


class SgWatchdog(threading.Thread):
	def __init__(self):
		super(SgWatchdog, self).__init__(name = 'conn_watcher')
		self.daemon = True
		self.watches = {}
		self.lock = threading.RLock()

	def add(self, threads, socket, reconnect):
		with self.lock:
			self.watches[socket] = (threads, reconnect)
		# XXX poke self to redo run loop noticing new add

	def run(self):
		def detect_bad_sockets(socket_list):
			closed = []
			for fd in socket_list:
				try:
					try:
						select.select([], [], [fd], 0)
						logger.debug('fd %s is ok (fd %d)' % (fd, fd.fileno()))
					except (select.error, socket.error) as se:
						if se[0] == socket.EBADF:
							logger.debug('fd %s got EBADF; pruning' % fd)
							closed.append(fd)
						else:
							raise se;
				except:
					logger.exception('unexpected other problem probing for closed fd')
			return closed

		while True:
			try:
				# If any watched socket closes, wait for associated threads to die, and invoke reconnect.
				# Note that passing a bad fd to select results in socket library throwing a EBADF exception,
				# which doesn't tell us which socket did that. In that case, I reprobe all the sockets one
				# by one looking for that exception.
				with self.lock:
					socket_list = self.watches.keys()
				logger.debug('sleep')
				try:
					(readable, writable, errored) = select.select([], [], socket_list, 1) # XXX timeout to detect adds, should be event-based
					logger.debug('wake: count r/w/e = %d/%d/%d' % (len(readable), len(writable), len(errored)))
				except (select.error, socket.error) as se:
					# This is kind of weird. The first time I select() on a closed socket I get a select.error,
					# and after that for the same socket, I get a socket.error. There's probably a reason for
					# this, but it seems confusing and fragile, and hopefully less so if I just catch whichever
					# one happens first and treat them the same.
					if se[0] == socket.EBADF:
						errored = detect_bad_sockets(socket_list)
					else:
						raise se;
				logger.debug('invoking %d cleanups' % len(errored))
				for bad in errored:
					with self.lock:
						CleanupAndRestart(self.watches.pop(bad)).start()
				logger.debug('done with cleanup; repeat')
			except:
				logger.exception('exception in watchdog thread')
