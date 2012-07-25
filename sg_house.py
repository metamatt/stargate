# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides the common glue between gateway modules, and the
# object model common to the whole system.

import gateways


class StargateDevice(object):
	pass

class StargateArea(object):
	pass

class StargateHouse(StargateArea):
	gateways = {}

	def __init__(self, config):
		self.gateways = gateways.load_all(self, config['gateways'])
