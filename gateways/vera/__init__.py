# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways.vera package init

import vera_gateway

def init(house, instance_name, gateway_config):
	hostname = gateway_config['gateway']['hostname']
	
	return vera_gateway.VeraGateway(house, instance_name, hostname)
