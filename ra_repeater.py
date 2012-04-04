# This module handles the TCP connection to the repeater,
# and provides an interface for getting/setting load status
# and sending commands to/from Ra2 devices.

import socket
import time

CRLF = '\r\n'

class RaRepeater(object):
	layout = None
	
	def __init__(self, layout):
		self.verbose = False
		self.readstash = ''
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

	def get_outputs_all(self):
		return self.get_output_levels_cond(self.layout.outputs.values(), '>', -1)
	
	def get_outputs_on(self):
		return self.get_output_levels_cond(self.layout.outputs.values(), '>', 0)

	def get_outputs_off(self):
		return self.get_output_levels_cond(self.layout.outputs.values(), '=', 0)

	def get_output_levels_cond(self, outputs, comparison, comparee):
		matches = []
		for o in outputs:
			cmd = '?OUTPUT,%s,1' % (o.iid)
			self.send(cmd)
			# XXX not sure how to demux the output stream. Maybe I should just treat it as totally async,
			# with monitoring enabled: ignore prompts & assume I can always talk; always be listening
			# from a separate async event loop which reads whatever it can (whether result of our command
			# or someone else's via monitoring) and builds a state cache, and when we want to know what
			# happened after a command like this, we just drain input and then get it from the state cache.
			response = self.readline()
			brightness = float(response.split(',')[-1])
			if (self.check_cond(brightness, comparison, comparee)):
				matches.append((repr(o), response))
			self.readprompt()
		return matches

	def check_cond(self, val1, op, val2):
		if op == '=':
			return val1 == val2
		if op == '<':
			return val1 < val2
		if op == '>':
			return val1 > val2
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
		
		prompt = self.read_until('login: ')
		self.send(username)
		prompt = self.read_until('password: ')
		self.send(password)
		self.readprompt()
		
	def enable_monitoring(self):
		self.send('#MONITORING,255,1')
		reply = self.readline()
		print reply
		self.readprompt()
		
	def send(self, cmd):
		if self.verbose:
			print 'debug: send %s' % repr(cmd)
		self.socket.send(cmd + CRLF)
		
	def readline(self):
		return self.read_until(CRLF).rstrip()

	def readprompt(self):
		prompt = self.read_until('GNET> ')
		skipped = prompt[:-6].rstrip() # discard the prompt itself
		if self.verbose and len(skipped) > 0:
			print 'debug: skipped %s' % repr(skipped)
		return skipped
		
	def read_until(self, terminator):
		while True:
			# see if we have what they're looking for
			pos = self.readstash.find(terminator)
			if pos != -1:
				# include terminator, return that part and keep the rest stashed
				pos += len(terminator)
				grabbed = self.readstash[:pos]
				self.readstash = self.readstash[pos:]
				if self.verbose:
					print 'debug: read return %s' % repr(grabbed)
					if len(self.readstash) > 0:
						print 'debug: read stash still has "%s"' % repr(self.readstash) # str([byte for byte in self.readstash])
				return grabbed
			# no, so read more
			try:
				chunk = self.socket.recv(1024)
				if self.verbose:
					print 'debug: read stash %s' % repr(chunk)
				self.readstash = self.readstash + chunk
			except socket.error:
				time.sleep(.1) # BUG: should select here
