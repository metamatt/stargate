# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways.synther package init

import synthesizer

def get_dependencies(gateway_config):
	# XXX This is a fairly messy way of calculating this, but at least it's self contained.
	# Really it would be cleaner to split gateway create and initialize, be able to at least
	# create the object without the constructor doing much, then ask it to fill in the
	# dependencies, and do what the constructor currently does later in init.
	deps = set()

	# These are all hardcoded, because they are.
	if gateway_config.get('bridges'):
		deps.add('radiora2')
		deps.add('powerseries')
	if gateway_config.get('ledbridges'):
		deps.add('radiora2')
		deps.add('powerseries')
	if gateway_config.get('delays'):
		deps.add('radiora2')

	# Paranoid is more complicated, but less hardcoded here, because its dependencies
	# actually vary according to the specific configuration.
	paranoid_watches = gateway_config.get('paranoid')
	for pw in paranoid_watches:
		deps.add(pw['gateway'])

	return deps

def init(house, instance_name, gateway_config):
	return synthesizer.Synthesizer(house, instance_name,
		gateway_config.get('bridges', []),
		gateway_config.get('ledbridges', []),
		gateway_config.get('delays', []),
		gateway_config.get('paranoid', []))
