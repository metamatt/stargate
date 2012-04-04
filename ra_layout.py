# This module handles the RadioRa2 project layout (from the configuration
# software, and available from the repeater's web server as DbXmlInfo.xml),
# and provides a high-level interface for working with its information in
# a structured way: areas, loads, and keypads.

import httplib
import logging
import xml.dom.minidom


class RaBase(object):
	def __init__(self, iid, name):
		self.iid = iid
		self.name = name
		
	def __repr__(self):
		return '%s %s: %s' % (self.__class__.__name__, self.iid, self.name)

class RaArea(RaBase):
	outputs = None
	
	def __init__(self, iid, name):
		super(RaArea, self).__init__(iid, name)
		self.outputs = list()
		
	def add_output(self, output):
		self.outputs.append(output)

class RaOutput(RaBase):
	area_id = None
	
	def __init__(self, iid, name, area):
		name = '%s (in %s)' % (name, area.name)
		super(RaOutput, self).__init__(iid, name)
		self.area = area
		area.add_output(self)

class RaKeypad(RaBase):
	def __init__(self, iid, name):
		super(RaKeypad, self).__init__(iid, name)


class RaLayout(object):
	db_dom = None
	db_xml = None
	
	def read_cached_db(self, cacheFileName):
		logging.info('Read DbXmlInfo from local file')
		# XXX would be nice if we could just do a HEAD request, but the
		# repeater's HTTP server doesn't respond to that. TBD how we
		# figure out when to cache, and when to get the file from the
		# repeater.
		cache = open('DbXmlInfo.xml')
		self.db_xml = cache.read()
		logging.info('Parse DbXmlInfo')
		self.db_dom = xml.dom.minidom.parseString(self.db_xml)

	def get_live_db(self, hostname):
		logging.info('Read DbXmlInfo from repeater')
		conn = httplib.HTTPConnection(hostname, 80)
		conn.request('GET', '/DbXmlInfo.xml')
		response = conn.getresponse()
		self.db_xml = response.read()
		logging.info('Parse DbXmlInfo')
		self.db_dom = xml.dom.minidom.parseString(self.db_xml)

	def map_db(self):
		logging.info('Build map from DbXmlInfo')
		self.areas = {}
		self.outputs = {}
		for areaTag in self.db_dom.getElementsByTagName('Area'):
			area_name = areaTag.attributes['Name'].value
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
			area_iid = areaTag.attributes['IntegrationID'].value

			area = self.areas[area_iid] = RaArea(area_iid, area_name)

			for outputTag in areaTag.getElementsByTagName('Output'):
				output_name = outputTag.attributes['Name'].value
				output_iid = outputTag.attributes['IntegrationID'].value
				self.outputs[output_iid] = RaOutput(output_iid, output_name, area)
			for deviceTag in areaTag.getElementsByTagName('Device'):
				# TODO: extract info about keypads
				pass
		logging.info('Done building DbXmlInfo map')
