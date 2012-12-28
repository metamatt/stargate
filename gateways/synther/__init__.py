# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways.synther package init

import synthesizer

def init(house, instance_name, gateway_config):
	bridges = gateway_config.bridges
	return synthesizer.Synthesizer(house, instance_name, bridges)
