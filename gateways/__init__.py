# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways package init

import importlib
import logging

logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


def load_all(sg_house, gateways_config):
	sg_house.gateways = {}
	gateway_map = sg_house.gateways

	# XXX quick and dirty hack to allow config file to set order; I should really figure out how
	# to preserve order of YAML file and just process it in order. What we've been doing is importing
	# the whole YAML config into a python dict, then just enumerating dict keys in arbitrary order.
	# What we'll do for now is look for an "order" key in the YAML file at the same level as the
	# gateway configs; if that exists, use it as the order to process the real gateways; otherwise
	# just fall back on the keys at this level (which is what we've been doing until now).
	gateway_order = gateways_config.order or gateways_config.keys()

	for gateway_module_name in gateway_order:
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
