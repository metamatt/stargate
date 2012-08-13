# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways package init

import importlib
import logging

logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


def load_all(sg_house, gateways_config):
	gateway_map = {}

	for gateway_module_name in gateways_config.keys():
		# Load gateway plugin code
		# gateway plugins are likely actually a package, not a module, but importlib calls it import_module, so...
		gateway_module = importlib.import_module('.' + gateway_module_name, __name__)
		# Locate gateway configuration
		config = gateways_config[gateway_module_name]
		if config.has_key('disabled') and config.disabled:
			logger.info('ignoring disabled gateway "%s"' % gateway_module_name)
			continue
		logger.info('loading gateway "%s"' % gateway_module_name)

		# XXX: may want facility for running multiple instances of the same gateway plugin, with unique names/config?
		gateway_instance_name = gateway_module_name # for now
		# Construct gateway
		gateway = gateway_module.init(sg_house, gateway_instance_name, config)
		
		# We maintain gateways as a map keyed by name
		gateway_map[gateway_instance_name] = gateway
	
	return gateway_map
