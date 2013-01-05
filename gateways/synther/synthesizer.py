# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Cross-device control for Stargate.
#
# This module provides Stargate devoce objects which bind and delegate
# to existing devices exposed by other gateways.
#

import logging
import time

from sg_util import AttrDict
import sg_house


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class Bridge(object):
	def __init__(self, synthesizer, params):
		logger.info('create bridge for %s' % str(params))
		self.synth = synthesizer
		house = synthesizer.house
		keys = params.keys()

		# Locate devices to operate on
		# XXX right now, behavior is hardcoded to handle radiora2<>powerseries the way I'm using them
		ra_dev = house.get_device_by_gateway_and_id('radiora2', params['radiora2'])
		dsc_zone = house.get_device_by_gateway_and_id('powerseries', 'zone:%d' % params['dsc_zone'])
		(dsc_partition, dsc_cmd_id) = map(int, str(params['dsc_cmd']))

		# Suck initial state from DSC and push into Lutron
		logger.debug('Currently: Lutron says %s; DSC says %s' % (ra_dev.is_on(), dsc_zone.is_open()))
		ra_dev.be_on(dsc_zone.is_open())

		# Watch when Lutron says to change it (Lutron button/remote/integration)
		def on_lutron_push(synthetic):
			logger.debug('lutron dev %d changed to %s %s' % (ra_dev.iid, ra_dev.is_on(), ' synthetic' if synthetic else ''))
			if ra_dev.is_on() != dsc_zone.is_open():
				logger.debug('telling dsc to toggle 020%d%d' % (dsc_partition, dsc_cmd_id))
				dsc_zone.gateway.send_user_command(dsc_partition, dsc_cmd_id)
			else:
				logger.debug('ignoring lutron dev-change for %d to already-current state %s' % (ra_dev.iid, ra_dev.is_on()))
		house.events.subscribe(ra_dev, on_lutron_push)

		# Watch when DSC says it did change (someone used an old-school switch)
		def on_physical_push(synthetic):
			logger.debug('dsc dev %d changed to %s' % (dsc_zone.zone_number, dsc_zone.is_open()))
			ra_dev.be_on(dsc_zone.is_open())
		house.events.subscribe(dsc_zone, on_physical_push)


class Synthesizer(sg_house.StargateGateway):
	def __init__(self, house, gateway_instance_name, bridges):
		super(Synthesizer, self).__init__(house, gateway_instance_name)
		self.bridges = []
		for bridge in bridges:
			self.bridges.append(Bridge(self, bridge))

	# public interface to StargateHouse
	def get_device_by_gateway_id(self, gateway_devid):
		# XXX this is uncalled since we don't create StargateDevices
		assert False
