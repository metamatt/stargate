# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways package init

import importlib


def load_all(sg_house, gateways_config):
	gateway_map = {}

	for gateway_module_name in gateways_config.keys():
		# gateway plugins are likely actually a package, not a module, but importlib calls it import_module, so...
		gateway_module = importlib.import_module('.' + gateway_module_name, __name__)
		config = gateways_config[gateway_module_name]
		gateway = gateway_module.init(sg_house, config)
		
		gateway_map[gateway.gateway_name] = gateway
	
	return gateway_map
