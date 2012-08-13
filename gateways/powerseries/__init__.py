# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways.powerseries package init

import dsc_gateway

def init(house, instance_name, gateway_config):
	return dsc_gateway.DscGateway(house, instance_name, gateway_config)
