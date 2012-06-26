# This module handles the RadioRa2 project layout (from the configuration
# software, and available from the repeater's web server as DbXmlInfo.xml),
# and provides a high-level interface for working with its information in
# a structured way: areas, loads, and keypads.
#
# The idea here is that RaLayout and friends model things very close to
# the way Lutron's XML file does. Then RaHouse can reinterpret and model
# things differently if it so chooses.

import httplib
import logging
import xml.dom.minidom

class LayoutBase(object):
	# Everything in a RaLayout has an iid and a name.
	def __init__(self, iid, name):
		self.iid = iid
		self.name = name

	def __repr__(self):
		return '%s %s: %s' % (self.__class__.__name__, self.iid, self.name)

	def get_iid(self):
		return self.iid

class Area(LayoutBase):
	# An Area also has a list of outputs.
	# XXX and keypads, shade groups, any other components?

	outputs = None

	def __init__(self, iid, name):
		super(Area, self).__init__(iid, name)
		self.outputs = list()

	def add_output(self, output):
		self.outputs.append(output)
		
	def get_outputs(self):
		return self.outputs

class Output(LayoutBase):
	# An Output has a type and lives in an area.
	
	area = None
	outputType = None

	def __init__(self, iid, name, outputType, area):
		super(Output, self).__init__(iid, name)
		self.area = area
		self.outputType = outputType
		area.add_output(self)

	def get_scoped_name(self):
		return self.area.name + ' / ' + self.name
		
	def get_type(self):
		return self.outputType

class Keypad(LayoutBase):
	# Keypad: XXX placeholder
	def __init__(self, iid, name):
		super(Keypad, self).__init__(iid, name)


class RaLayout(object):
	db_dom = None
	db_xml = None
	areas = {} # map from iid (int) to object (Area)
	outputs = {} # map from iid (int) to object (Output)
	keypads = {}
	
	def read_cached_db(self, cacheFileName):
		logging.info('Read DbXmlInfo from local file')
		# XXX would be nice if we could just do a HEAD request, but the
		# repeater's HTTP server doesn't respond to that. TBD how we
		# figure out when to cache, and when to get the file from the
		# repeater.
		cache = open('DbXmlInfo.xml')
		self._setDbXml(cache.read())
		
	def _setDbXml(self, xmlData):
		self.db_xml = xmlData
		logging.info('Parse DbXmlInfo')
		self.db_dom = xml.dom.minidom.parseString(self.db_xml)
		logging.info('Done parsing DbXmlInfo')

	def get_live_db(self, hostname):
		logging.info('Read DbXmlInfo from repeater')
		conn = httplib.HTTPConnection(hostname, 80)
		conn.request('GET', '/DbXmlInfo.xml')
		response = conn.getresponse()
		self._setDbXml(response.read())

	def map_db(self):
		logging.info('Build map from DbXmlInfo')
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
			area_iid = int(areaTag.attributes['IntegrationID'].value)

			area = self.areas[area_iid] = Area(area_iid, area_name)

			for outputTag in areaTag.getElementsByTagName('Output'):
				output_name = outputTag.attributes['Name'].value
				output_iid = int(outputTag.attributes['IntegrationID'].value)
				output_type = outputTag.attributes['OutputType'].value
				self.outputs[output_iid] = Output(output_iid, output_name, output_type, area)
			for deviceTag in areaTag.getElementsByTagName('Device'):
				# TODO: extract info about keypads
				pass
		logging.info('Done building DbXmlInfo map')

	def get_output_ids(self):
		return self.outputs.keys()
	
	def get_outputs(self):
		return self.outputs.values()
	
	def get_areas(self):
		return self.areas.values()
