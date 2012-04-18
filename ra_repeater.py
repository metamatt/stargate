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
	# Super cheap temporary thing for now; this will be replaced by something better
	outputLevels = None
	repeater = None
	
	def __init__(self, repeater):
		self.outputLevels = {}
		self.repeater = repeater
	
	def setLevel(self, id, value):
		id = int(id) # XXX
		value = float(value) # XXX
		self.outputLevels[id] = value
	
	def getLevel(self, id):
		id = int(id) # XXX
		return self.outputLevels[id]
		
	def refresh(self, id):
		self.repeater.repeaterCommand('?OUTPUT,%d,1' % int(id))
	
	def refreshAll(self):
		# async, request refresh
		for id in self.repeater.layout.outputs:
			self.refresh(id)
		# XXX need way to tell it actually happened

class RaRepeater(object):
	layout = None
	state = None
	cache = None
	
	def __init__(self, layout):
		self.verbose = False
		self.layout = layout
	
	def set_verbose(self, verbosity):
		self.verbose = verbosity
		
	def dump_all_levels(self):
		self.dump_output_levels(self.layout.outputs.values())
		
	def dump_room_levels(self, area_iid):
		self.dump_output_levels(self.outputs_for_area(area_iid))
		
	def dump_all_on(self):
		self.dump_output_levels_cond(self.layout.outputs.values(), '>', 0)
		
	def dump_output_levels(self, outputs):
		self.dump_output_levels_cond(outputs, '>', -1)
		
	def dump_output_levels_cond(self, outputs, comparison, comparee):
	 	matches = self.get_output_levels_cond(outputs, comparison, comparee)
		for m in matches:
			print m[0] + ' --> ' + m[1]

	def get_output_level(self, output_iid):
		levels = self.get_output_levels_cond([self.layout.outputs[output_iid]])
		return levels[0][1]

	def get_outputs_all(self):
		return self.get_output_levels_cond(self.layout.outputs.values())
	
	def get_outputs_on(self):
		return self.get_output_levels_cond(self.layout.outputs.values(), '>', 0)

	def get_outputs_off(self):
		return self.get_output_levels_cond(self.layout.outputs.values(), '=', 0)

	def get_output_levels_cond(self, outputs, comparison = 'always', comparee = '-1'):
		matches = []
		for o in outputs:
			level = self.cache.getLevel(o.iid)
			if (self.check_cond(level, comparison, comparee)):
				matches.append((o, level))
		return matches

	def check_cond(self, val1, op, val2):
		if op == '=':
			return val1 == val2
		if op == '<':
			return val1 < val2
		if op == '>':
			return val1 > val2
		if op == 'always':
			return True
		raise 'Unimplemented condition'
		
	def outputs_for_area(self, area_iid):
		#return [self.outputs[oid] for oid in self.layout.areas[area_iid].output_ids]
		return self.layout.areas[area_iid].outputs
		
	def all_on(self):
		self.all_to(100)

	def all_off(self):
		self.all_to(0)
		
	def all_to(self, level):
		pass # XXX write and test this when people aren't asleep!

	def room_on(self, area_iid):
		self.room_to(area_iid, 100)

	def room_off(self, area_iid):
		self.room_to(area_iid, 0)
		
	def room_to(self, area_iid, level):
		for output in self.outputs_for_area(area_iid):
			print "should set %s to %s" % (repr(output), str(level))
		# XXX finish and test this when people aren't asleep!

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

		self.cache = OutputCache(self)
		self.cache.refreshAll()
		
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
		pattern = re.compile('~OUTPUT,(\d+),1,(\d+.\d+)')
		match = pattern.search(line) # XXX: match instead of search, once I figure out the \rGNET issue
		if match:
			output = int(match.group(1))
			level = float(match.group(2))
			print "match %s -> %d:%g" % (match.group(), output, level)
			self.cache.setLevel(output, level)

	def startListenThread(self):
		class RepeaterListener(threading.Thread):
			repeater = None

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
