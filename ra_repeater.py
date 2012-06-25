# This module handles the TCP connection to the repeater,
# and provides an interface for getting/setting load status
# and sending commands to/from Ra2 devices.
#
# Rewrite in progress, after which, this should say:
#
# This module handles the TCP connection to the repeater,
# and listens to it in monitor mode to build a cache of
# device state for the entire system. It provides a low-level
# interface for querying and changing the state of outputs
# and devices.

import re
import select
import socket
import threading

# states we recognize in repeater listener
STATE_FRESH_CONNECTION, STATE_PROCESSING, STATE_WANT_LOGIN, STATE_WANT_PASSWORD, STATE_READY = range(5)
# repeater responses that are all she wrote, and won't be followed by CRLF
ra_prompts = set(['login: ', 'password: ', 'GNET> '])
CRLF = '\r\n'

class OutputCache(object):
	# Low-level cache of last seen level for each device (output, button, led)
	outputLevels = None
	repeater = None
	
	def __init__(self, repeater):
		self.outputLevels = {}
		self.repeater = repeater
	
	def setLevel(self, iid, level):
		# should be called only by RaRepeater.repeaterReply()
		self.outputLevels[iid] = level
	
	def getLevel(self, iid):
		iid = int(iid) # XXX callers should use correct type
		return self.outputLevels[iid]
		
	def refresh(self, iid):
		iid = int(iid) # XXX callers should use correct type
		# async, request refresh
		self.repeater.repeaterCommand('?OUTPUT,%d,1' % iid)
	
	def refreshAll(self):
		for iid in self.repeater.knownOutputs:
			self.refresh(iid)
		# XXX that was async; should we provide sync version?

class RaRepeater(object):
	state = None
	cache = None
	knownOutputs = None
	
	def __init__(self):
		self.verbose = False
	
	def set_verbose(self, verbosity):
		self.verbose = verbosity
	
	def set_outputs_to_cache(self, iids):
		self.cache = OutputCache(self)
		self.knownOutputs = iids
		self.cache.refreshAll()
	
	def get_output_level(self, output_iid):
		return self.cache.getLevel(output_iid)
		return levels[0][1]

	def set_output_level(self, output_iid, level):
		self.repeaterCommand('#OUTPUT,%d,1,%g' % (output_iid, level))

	def connect(self, hostname, username, password):
		self.hostname = hostname
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.connect((hostname, 23))
		self.socket.setblocking(0)
		self.state = STATE_FRESH_CONNECTION
		self.startListenThread()

		self.waitForState(STATE_WANT_LOGIN)
		self.repeaterCommand(username)
		self.waitForState(STATE_WANT_PASSWORD)
		self.repeaterCommand(password)
		self.waitForState(STATE_READY)
		self.enable_monitoring()
		
	def enable_monitoring(self):
		self.repeaterCommand('#MONITORING,255,1')

	def repeaterCommand(self, cmd):
		self._setState(STATE_PROCESSING)
		if self.verbose:
			print 'debug: send %s' % repr(cmd)
		self.socket.send(cmd + CRLF)

	def repeaterReply(self, line):
		if self.verbose:
			print 'debug: reply %s' % repr(line)
		if line == 'GNET> ':
			self._setState(STATE_READY)
		elif line == 'login: ':
			self._setState(STATE_WANT_LOGIN)
		elif line == 'password: ':
			self._setState(STATE_WANT_PASSWORD)

		# TODO: more substantive processing of real commands
		# - should handle output, led, and button
		# - should announce this happened for historical logging
		# - should cache value for future gets (that's all this does now)
		pattern = re.compile('~OUTPUT,(\d+),1,(\d+.\d+)')
		match = pattern.search(line) # XXX: match instead of search, once I figure out the \rGNET issue
		if match:
			output = int(match.group(1))
			level = float(match.group(2))
			print "match %s -> device %d set level %g" % (match.group(), output, level)
			self.cache.setLevel(output, level)

	def startListenThread(self):
		class RepeaterListener(threading.Thread):
			repeater = None
			daemon = True

			def __init__(self, repeater):
				super(RepeaterListener, self).__init__()
				self.repeater = repeater

			def run(self):
				sock = self.repeater.socket
				verbose = self.repeater.verbose and False
				unprocessed = ''

				while True:
					# Run loop:
					# - block until socket is readable, then read whatever we can
					# - append new data to 'unprocessed'
					# - if 'unprocessed' contains any complete lines of input,
					#   send them over to main thread
					if verbose:
						print 'debug: listener thread block on input'
					(readable, writable, errored) = select.select([sock], [], [])
					if verbose:
						print 'debug: listener thread woke for input'
					assert readable == [sock]
					newInput = sock.recv(1024)
					# XXX: I don't know what embedded NUL bytes mean (e.g. after GNET prompt), but ignore them.
					newInput = newInput.replace('\x00', '')
					if verbose:
						print 'debug: listener thread read %d bytes: "%s"' % (len(newInput), repr(newInput))
					unprocessed += newInput
					lines = unprocessed.split(CRLF)
					if lines[-1] in ra_prompts:
						unprocessed = ''
					else:
						unprocessed = lines.pop()
					for line in lines:
						self.repeater.repeaterReply(line)

		self.stateEvent = threading.Event()
		self.listener = RepeaterListener(self)
		self.listener.start()
	
	def _setState(self, state):
		if self.verbose:
			print 'debug: state now %d' % state
		self.state = state
		# wake anyone waiting for this state change
		self.stateEvent.set()

	def waitForState(self, state):
		if self.verbose:
			print 'debug: want state %d' % state
		while self.state != state:
			self.stateEvent.clear()
			if self.state == state:
				print 'hahahaha!'
				break
			if self.verbose:
				print 'debug: wait for state change (now %d)' % self.state
			self.stateEvent.wait()
		if self.verbose:
			print 'debug: state wait satisfied'
