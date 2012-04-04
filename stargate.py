#! /usr/bin/env python
#
# Simple test module for Lutron RadioRa2 network integration.
# Author: matt@ginzton.net
#
# Bugs:
# - simple, incomplete
# - should reconnect automatically if connection drops

import httplib
import optparse
import socket
import sys
import time
import xml.dom.minidom

CRLF = '\r\n'

class Area(object):
	def __init__(self, iid, name):
		self.iid = iid
		self.name = name
		self.output_ids = []
		
	def __repr__(self):
		return 'Area %s: %s' % (self.iid, self.name)

class Output(object):
	def __init__(self, iid, name, area_id):
		self.iid = iid
		self.name = name
		self.area_id = area_id
		
	def __repr__(self):
		return 'Output %s: %s (%s)' % (self.iid, self.name, self.area_id)

class RadioRa(object):
	def __init__(self):
		self.verbose = False
		self.readstash = ''
	
	def set_verbose(self, verbosity):
		self.verbose = verbosity
		
	def get_db(self, hostname):
		if True:
			cache = open('DbXmlInfo.xml')
			self.db_xml = cache.read()
		else:
			conn = httplib.HTTPConnection(hostname, 80)
			conn.request('GET', '/DbXmlInfo.xml')
			response = conn.getresponse()
			self.db_xml = response.read()
		self.db_dom = xml.dom.minidom.parseString(self.db_xml)

	def map_db(self):
		self.areas = {}
		self.outputs = {}
		for area in self.db_dom.getElementsByTagName('Area'):
			area_name = area.attributes['Name'].value
			if area_name == 'Root Area':
				# I'm not sure what if anything I want to do with the root area --
				# naive use of the DOM means it "contains" all the device groups and
				# outputs, which is kinda true, but losing the info about how they
				# group into areas/rooms. So for now at least, I'll skip this,
				# iterate the leaf areas, and then rebuild an "all" zone.
				#
				# Note for RadioRa, there's only one level of hierarchy, with a bunch
				# of leaf areas inside the root area. For Homeworks, this probably
				# isn't true (judging from the Lutron sample scenes in their app),
				# so likely the data format actually is a general tree where containment
				# means something, and I should try to model that -- by noting which
				# areas contain areas, but not by flattening areas->outputs entirely
				# the way the DOM getElementsByTagName does.
				continue
			area_iid = area.attributes['IntegrationID'].value
			outputs = area.getElementsByTagName('Output')
			self.areas[area_iid] = Area(area_iid, area_name)
			for output in outputs:
				output_name = output.attributes['Name'].value
				output_iid = output.attributes['IntegrationID'].value
				self.outputs[output_iid] = Output(output_iid, output_name, area_iid)
				self.areas[area_iid].output_ids.append(output_iid)
				
	def dump_all_levels(self):
		self.dump_output_levels(self.outputs.values())
		
	def dump_room_levels(self, area_iid):
		self.dump_output_levels(self.outputs_for_area(area_iid))
		
	def dump_all_on(self):
		self.dump_output_levels_cond(self.outputs.values(), '>', 0)
		
	def dump_output_levels_cond(self, outputs):
		self.dump_output_levels(outputs, '>', -1)
		
	def dump_output_levels_cond(self, outputs, comparison, comparee):
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
				print repr(o) + " --> " + response
			self.readprompt()

	def check_cond(self, val1, op, val2):
		if op == '=':
			return val1 == val2
		if op == '<':
			return val1 < val2
		if op == '>':
			return val1 > val2
		raise 'Unimplemented condition'
		
	def outputs_for_area(self, area_iid):
		return [self.outputs[oid] for oid in self.areas[area_iid].output_ids]
		
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

if __name__ == '__main__':
		# When invoked directly, parse the command line to find hostname and password,
		# then connect, log in, and enter a monitoring loop which just prints system events
		# until killed.
		
		# parse command line
		p = optparse.OptionParser()
		p.add_option('-H', '--hostname', default = 'lutron-radiora', help = 'network hostname for main repeater, default lutron-radiora')
		p.add_option('-U', '--username', default = 'lutron', help = 'username for repeater telnet login')
		p.add_option('-P', '--password', default = 'integration', help = 'password for repeater telnet login')
		p.add_option('-V', '--verbose', action = 'store_true', help = 'enable debug output')
		(options, args) = p.parse_args()
		
		# connect and log in
		r = RadioRa()
		if options.verbose:
			r.set_verbose(True)
		r.get_db(options.hostname)
		r.map_db()
		r.connect(options.hostname, options.username, options.password)
		#r.enable_monitoring()
		#r.dump_all_levels()
		#r.room_to('11', 75)
		r.dump_all_on()
		