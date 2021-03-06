# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways.vera package init

import vera_gateway

def get_dependencies(gateway_config):
	return set()

def init(house, instance_name, gateway_config):
	hostname = gateway_config.gateway.hostname
	poll_interval = gateway_config.gateway.poll_interval
	
	return vera_gateway.VeraGateway(house, instance_name, hostname, poll_interval)
