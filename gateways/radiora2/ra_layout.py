# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system.
#
# This module handles the RadioRa2 project layout (from the configuration
# software, and available from the repeater's web server as DbXmlInfo.xml),
# and provides a semi-high-level interface for working with its information
# in a structured way: areas, outputs, and devices. (At this layer, we
# continue to use Lutron terminology. "Devices" are input devices; mostly
# keypads, and also the collections of buttons on things like the main
# repeater and the visor control receiver; they're modeled as collections
# of buttons and LEDs, and all cases I know about are equivalent to keypads,
# but Lutron calls them "devices".)
#
# The idea here is that RaLayout and friends model things very close to
# the way Lutron's XML file does. Then RaHouse can reinterpret and model
# things differently if it so chooses.

import httplib
import logging
import xml.dom.minidom


logger = logging.getLogger(__name__)


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
	# An Area additionally has a list of outputs and a list of devices.
	# XXX The Lutron XML file also includes information about device groups,
	#     shade groups, and area nesting which we don't (currently) model.

	outputs = None
	devices = None

	def __init__(self, iid, name):
		super(Area, self).__init__(iid, name)
		self.outputs = list()
		self.devices = list()

	@staticmethod
	def from_xml(area_element):
		area_name = area_element.attributes['Name'].value
		area_iid = int(area_element.attributes['IntegrationID'].value)
		return Area(area_iid, area_name)

	def add_output(self, output):
		self.outputs.append(output)
		
	def get_outputs(self):
		return self.outputs

	def add_device(self, device):
		self.devices.append(device)

	def get_devices(self):
		return self.devices


class Output(LayoutBase):
	# An Output additionally has an associated area and a type (shade, light, etc).

	area = None
	outputType = None

	def __init__(self, iid, name, outputType, area):
		super(Output, self).__init__(iid, name)
		self.area = area
		self.outputType = outputType
		area.add_output(self)
	
	@staticmethod
	def from_xml(output_element, area):
		output_name = output_element.attributes['Name'].value
		output_iid = int(output_element.attributes['IntegrationID'].value)
		output_type = output_element.attributes['OutputType'].value
		return Output(output_iid, output_name, output_type, area)

	def get_type(self):
		return self.outputType


class Device(LayoutBase):
	# A Device additionally has an associated area and a type (pico, seetouch, etc),
	# a list of buttons (actually a map from button id to label), and a list of LEDs.

	area = None
	deviceType = None
	buttons = None
	leds = None

	def __init__(self, iid, name, deviceType, area):
		super(Device, self).__init__(iid, name)
		self.area = area
		self.deviceType = deviceType
		area.add_device(self)
		self.buttons = dict()
		self.leds = list()

	@staticmethod
	def from_xml(device_element, area):
		def get_fixed_button_name(devtype, comp):
			map = None
			if devtype == 'PICO_KEYPAD': # up to 5 buttons, no engraving, relatively fixed function
				map = { 2: 'Top', 3: 'Middle', 4: 'Bottom', 5: 'Raise', 6: 'Lower' }
			elif devtype == 'SEETOUCH_TABLETOP_KEYPAD': # 1-3 sets of raise/lower buttons
				map = { 20: 'Right column lower', 21: 'Right column raise', 22: 'Middle column lower', 23: 'Middle column raise',
				        24: 'Left column lower', 25: 'Left column raise' }
			elif devtype == 'SEETOUCH_KEYPAD' or devtype == 'HYBRID_SEETOUCH_KEYPAD': # 1 column, 0-2 sets of raise/lower buttons
				map = { 16: 'Top lower', 17: 'Top raise', 18: 'Bottom lower', 19: 'Bottom raise' }
			if map is not None and map.has_key(comp):
				return '[%s]' % map[comp]
			return None

		device_name = device_element.attributes['Name'].value
		device_iid = int(device_element.attributes['IntegrationID'].value)
		device_type = device_element.attributes['DeviceType'].value
		device = Device(device_iid, device_name, device_type, area)
		for component_element in device_element.getElementsByTagName('Component'):
			comp_number = int(component_element.attributes['ComponentNumber'].value)
			comp_type = component_element.attributes['ComponentType'].value
			if comp_type == 'BUTTON':
				button_element = component_element.getElementsByTagName('Button')[0]
				try:
					label = button_element.attributes['Engraving'].value
				except KeyError:
					label = get_fixed_button_name(device_type, comp_number)
					if not label:
						label = button_element.attributes['Name'].value
				device.buttons[comp_number] = label
			elif comp_type == 'LED':
				device.leds.append(comp_number)
		return device
		
	def ignore(self):
		self.buttons = dict()
		self.leds = list()

	def get_type(self):
		return self.deviceType
	
	def get_button_component_ids(self):
		return self.buttons.keys()
	
	def get_led_component_ids(self):
		return self.leds


class RaLayout(object):
	db_dom = None
	db_xml = None
	areas = {} # map from iid (int) to object (Area)
	outputs = {} # map from iid (int) to object (Output)
	devices = {} # map from iid (int) to object (Device)
	ignore_devices = None
	
	def __init__(self, ignore_devices = None):
		self.ignore_devices = ignore_devices
	
	def read_cached_db(self, cacheFileName):
		logger.info('Read DbXmlInfo from local file')
		# XXX would be nice if we could just do a HEAD request, but the
		# repeater's HTTP server doesn't respond to that. TBD how we
		# figure out when to cache, and when to get the file from the
		# repeater.
		cache = open('DbXmlInfo.xml')
		self._setDbXml(cache.read())

	def _setDbXml(self, xmlData):
		self.db_xml = xmlData
		logger.info('Parse DbXmlInfo')
		self.db_dom = xml.dom.minidom.parseString(self.db_xml)
		logger.info('Done parsing DbXmlInfo')

	def get_live_db(self, hostname):
		logger.info('Read DbXmlInfo from repeater')
		conn = httplib.HTTPConnection(hostname, 80)
		conn.request('GET', '/DbXmlInfo.xml')
		response = conn.getresponse()
		self._setDbXml(response.read())

	def map_db(self):
		logger.info('Build map from DbXmlInfo')
		for area_element in self.db_dom.getElementsByTagName('Area'):
			area = Area.from_xml(area_element)
			if area.name == 'Root Area':
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
			self._add_area(area)

			for output_element in area_element.getElementsByTagName('Output'):
				self._add_output(Output.from_xml(output_element, area))

			for device_element in area_element.getElementsByTagName('Device'):
				self._add_device(Device.from_xml(device_element, area))
				
		logger.info('Done building DbXmlInfo map')

	def _add_area(self, area):
		self.areas[area.iid] = area

	def _add_output(self, output):
		self.outputs[output.iid] = output

	def _add_device(self, device):
		if device.iid in self.ignore_devices:
			device.ignore()
		self.devices[device.iid] = device

	def get_output_ids(self):
		return self.outputs.keys()

	def get_outputs(self):
		return self.outputs.values()

	def get_device_ids(self):
		return self.devices.keys()

	def get_devices(self):
		return self.devices.values()

	def get_device(self, iid):
		return self.devices[iid]

	def get_areas(self):
		return self.areas.values()
