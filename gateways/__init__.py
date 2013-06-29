# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways package init

import importlib
import logging
import sg_util

logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


def load_all(sg_house, gateways_config):
	sg_house.gateways = {}

	# To load gateways in correct dependency order, this proceeds in 3 phases.
	# 1) Load all gateways, query their dependencies
	# 2) Build dependency graph, and disable any gateways with broken dependencies
	# 3) Initialize gateways in order that does not violate dependencies

	# 1: iterate configured gateways, load modules and query dependencies
	gateway_info_map = {}
	for gateway_module_name in gateways_config.keys():
		# Locate gateway configuration
		config = gateways_config[gateway_module_name]
		if config.get('disabled', False):
			logger.info('ignoring disabled gateway "%s"' % gateway_module_name)
			continue

		try:
			logger.info('loading gateway "%s"' % gateway_module_name)
			# Load gateway plugin code
			gateway_module = importlib.import_module('.' + gateway_module_name, __name__)
			# query dependencies
			deps = gateway_module.get_dependencies(config);

			gateway_info_map[gateway_module_name] = sg_util.AttrDict({
				'name': gateway_module_name,
				'config': config,
				'module': gateway_module,
				'deps': deps,
				'reverse_deps': set()
			})

		except Exception as ex:
			logger.error('gateway "%s" failed to load at all' % gateway_module_name)
			logger.exception(ex)

	# 2: build "dependency graph" -- not much fancier than we already have, but add reverse pointers,
	# and partition into initial ready/pending sets
	ready = list()
	pending = list()
	for gateway_info in gateway_info_map.values():
		if gateway_info.deps:
			for depname in gateway_info.deps:
				target = gateway_info_map.get(depname)
				if target:
					target.reverse_deps.add(gateway_info.name)
			pending.append(gateway_info)
		else:
			ready.append(gateway_info)

	# 3: iterate "toplogical sort":
	# - find gateways with no dependencies, initialize them
	#   - on successful load, remove dependencies on this gateway
	# - repeat until there are no gateways with no dependencies
	# This is a little more complicated than it would be to just calculate an ordering that looks to work
	# and then apply it, but we do it this way so that if a gateway fails to initialize,  we don't even try
	# to initialize anything that depends on it.

	# Repeat till we end up with an empty list:
	while ready:
		# Grab any ready gateway
		gateway_info = ready.pop()
		assert(not gateway_info.deps)

		# Initialize it
		try:
			logger.info('initialize gateway "%s"' % gateway_info.name)
			# Construct gateway
			gateway = gateway_info.module.init(sg_house, gateway_info.name, gateway_info.config)
			
			# Once gateway is initialized, immediately add it to the house, so that further gateways can find it
			sg_house.gateways[gateway_info.name] = gateway

		except Exception as ex:
			logger.error('gateway "%s" failed to initialize and will not be loaded' % gateway_info.name)
			logger.exception(ex)
			continue

		# Update progress of topological sort: remove any satisfied dependency links
		for depname in gateway_info.reverse_deps:
			source = gateway_info_map[depname]
			assert gateway_info.name in source.deps
			source.deps.remove(gateway_info.name)

			# And if that clears the way for another module, move it from pending to ready
			if not source.deps:
				pending.remove(source)
				ready.append(source)

		# Just for cleanliness, clear this module's reverse_deps since we've handled them
		# (Nothing will look at this again, so it doesn't actually matter.)
		gateway_info.reverse_deps.clear()

	# If anything is still pending, too bad.
	for gateway_info in pending:
		assert(gateway_info.deps)
		logger.error('gateway "%s" ignored due to broken dependencies %s' % (gateway_info.name, gateway_info.deps))
