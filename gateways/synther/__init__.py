# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways.synther package init

import synthesizer

def init(house, instance_name, gateway_config):
	bridges = gateway_config.get('bridges', [])
	ledbridges = gateway_config.get('ledbridges', [])
	delays = gateway_config.get('delays', [])
	paranoid = gateway_config.get('paranoid', [])
	return synthesizer.Synthesizer(house, instance_name,
		gateway_config.get('bridges', []),
		gateway_config.get('ledbridges', []),
		gateway_config.get('delays', []),
		gateway_config.get('paranoid', []))
