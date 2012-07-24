# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# stargate.gateways.radiora2 package init

import ra_house
import ra_layout
import ra_repeater

def build_house(repeater_config):
	layout = ra_layout.RaLayout(ignore_devices = repeater_config['layout']['ignore_keypads'])
	if repeater_config.has_key('cached_database'):
		layout.read_cached_db(repeater_config['cached_database'])
	else:
		layout.get_live_db(repeater_config['hostname'])
	layout.map_db()

	repeater = ra_repeater.RaRepeater()
	repeater.connect(repeater_config['hostname'], repeater_config['username'], repeater_config['password'])

	house = ra_house.House(repeater, layout)
	return house
