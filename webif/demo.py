# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Simple web UI for Stargate.

import datetime
import dateutil.parser
import time

from flask import Flask, request, render_template, redirect, url_for

app = Flask(__name__)
house = None # will be set by stash_house()


@app.route('/')
def root():
	return render_template('index.html')

# generic device lookup redirects to canonical URL for device, named by class
@app.route('/device/<int:dev_id>')
def get_device(dev_id):
	device = house.get_device_by_id(dev_id)
	return redirect(url_for('get_%s' % device.devclass, dev_id = dev_id))

#####################
# Controls
################

@app.route('/controls/', defaults = {'filterdesc': ''})
@app.route('/controls/<filterdesc>')
def enumerate_controls(filterdesc):
	return enumerate_devices_in_class(filterdesc, 'control')

@app.route('/control/<int:dev_id>')
def get_control(dev_id):
	# XXX hack to allow calling activate_control with a GET request, for easy hyperlinking
	if request.values.has_key('action'):
		return activate_control(dev_id)
	control = house.get_device_by_id(dev_id)
	if control.devclass != 'control':
		return not_found()
	return render_template('output.html', device = control)

@app.route('/control/<int:dev_id>', methods = ['POST'])
def activate_control(dev_id):
	params = request.values
	button_id = int(params['button_id'])
	action = params['action']
	control = house.get_device_by_id(dev_id)
	button = control.get_button(button_id)
	if action == 'press':
		button.set_button_state(True)
	elif action == 'release':
		button.set_button_state(False)
	elif action == 'pulse':
		button.set_button_state(True)
		time.sleep(0.2)
		button.set_button_state(False)
	# XXX should make this respond to async operation when it completes; for now just wait a bit
	# and show the device details page
	time.sleep(0.3)
	return redirect(url_for('get_control', dev_id = dev_id))

#####################
# Outputs
################

@app.route('/outputs/', defaults = {'filterdesc': ''})
@app.route('/outputs/<filterdesc>')
def enumerate_outputs(filterdesc):
	return enumerate_devices_in_class(filterdesc, 'output')

@app.route('/output/<int:dev_id>')
def get_output(dev_id):
	output = house.get_device_by_id(dev_id)
	if output.devclass != 'output':
		return not_found()
	return render_template('output.html', device = output)

@app.route('/output/<int:dev_id>', methods = ['POST'])
def set_output(dev_id):
	params = request.form
	output = house.get_device_by_id(dev_id)
	state = params['state']
	if state == 'level':
		level = float(params['level'])
		output.set_level(level)
	else:
		output.go_to_state(state)
	# XXX should make this respond to async operation when it completes; for now just wait a bit
	# and show the device details page
	time.sleep(0.3)
	return redirect(url_for('get_output', dev_id = dev_id))

@app.route('/output/multi/to_state', methods = ['POST'])
def set_outputs_to_state():
	params = request.form
	state = params['state']
	dev_ids = map(int, params['outputs'].split(','))
	for dev_id in dev_ids:
		output = house.get_device_by_id(dev_id)
		output.go_to_state(state)
	# XXX should make this respond to async operation when it completes; for now just wait a bit
	# hack: show the page for the outputs in the area containing the last device, filtered by device type
	time.sleep(0.2 * len(dev_ids))
	return redirect(url_for('enumerate_outputs_by_area', area_id = output.area.area_id, filterdesc = output.devtype))

#####################
# Sensors
################

@app.route('/sensors/', defaults = {'filterdesc': ''})
@app.route('/sensors/<filterdesc>')
def enumerate_sensors(filterdesc):
	return enumerate_devices_in_class(filterdesc, 'sensor')

@app.route('/sensor/<int:dev_id>')
def get_sensor(dev_id):
	sensor = house.get_device_by_id(dev_id)
	if sensor.devclass != 'sensor':
		return not_found()
	return render_template('output.html', device = sensor)

#####################
# Areas
################

@app.route('/areas/', defaults = {'filterdesc': ''})
@app.route('/areas/<filterdesc>')
def enumerate_areas(filterdesc):
	devfilter = house.parse_devfilter_description(descriptor = filterdesc)
	areas = house.get_areas_filtered_by(devfilter)
	return render_template('areaList.html', areas = areas, active_filter = devfilter)

@app.route('/area/<int:area_id>')
def get_area(area_id):
	return redirect(url_for('enumerate_devices_by_area', area_id = area_id))

@app.route('/area/<int:area_id>/devices/', defaults = {'filterdesc': ''})
@app.route('/area/<int:area_id>/devices/<filterdesc>')
def enumerate_devices_by_area(area_id, filterdesc):
	return enumerate_devices_in_class_by_area(area_id, filterdesc, None)
	
@app.route('/area/<int:area_id>/outputs/', defaults = {'filterdesc': ''})
@app.route('/area/<int:area_id>/outputs/<filterdesc>')
def enumerate_outputs_by_area(area_id, filterdesc):
	return enumerate_devices_in_class_by_area(area_id, filterdesc, 'output')

@app.route('/area/<int:area_id>/controls/', defaults = {'filterdesc': ''})
@app.route('/area/<int:area_id>/controls/<filterdesc>')
def enumerate_controls_by_area(area_id, filterdesc):
	return enumerate_devices_in_class_by_area(area_id, filterdesc, 'control')

@app.route('/area/<int:area_id>/sensors/', defaults = {'filterdesc': ''})
@app.route('/area/<int:area_id>/sensors/<filterdesc>')
def enumerate_sensors_by_area(area_id, filterdesc):
	return enumerate_devices_in_class_by_area(area_id, filterdesc, 'sensor')

#####################
# Helpers
################

def enumerate_devices_in_class_by_area(area_id, filterdesc, devclass):
	area = house.get_area_by_id(area_id)
	devfilter = house.parse_devfilter_description(devclass = devclass, descriptor = filterdesc)
	devices = area.get_devices_filtered_by(devfilter)
	return render_template('outputList.html', area_filter = area, devices = devices, active_filter = devfilter)

def enumerate_devices_in_class(filterdesc, devclass):
	devfilter = house.parse_devfilter_description(devclass = devclass, descriptor = filterdesc)
	devices = house.get_devices_filtered_by(devfilter)
	return render_template('outputList.html', devices = devices, active_filter = devfilter)

#####################
# Plumbing
################

@app.route('/debug_break')
def debug_break():
	if app.debug:
		# Cause an exception so the debugger will step in
		raise Exception('debug break requested')
	else:
		# Hide from prying eyes by chaining to our 404 handler.
		return not_found()

@app.errorhandler(404)
def not_found(error = None):
	return render_template('error.html', request_path = request.path, referrer = request.referrer), 404

def seconds_today():
	now = datetime.datetime.now()
	today = now.replace(hour = 0, minute = 0, second = 0, microsecond = 0)
	return now - today

@app.context_processor
def inject_house():
	return dict(house = house, debug = app.debug, seconds_today = seconds_today)

def human_readable_timedelta(delta, text_if_none = 'unknown'):
	if not delta:
		return text_if_none
	if type(delta) != datetime.timedelta:
		delta = datetime.timedelta(seconds = delta)
	if delta == datetime.timedelta(0): # XXX should we consider time less than a second as 'right now' or 'less than a second'?
		return 'right now' # XXX in some contexts, 'no time' -- 'changed no time ago', 'changed right now', 'on since right now'...

	days = delta.days
	hours, remainder = divmod(delta.seconds, 3600)
	minutes, seconds = divmod(remainder, 60)
	
	tokens = []
	tokens.append('%d day%s' % (days, '' if days == 1 else 's')) if days else None
	tokens.append('%d hour%s' % (hours, '' if hours == 1 else 's')) if hours else None
	tokens.append('%d minute%s' % (minutes, '' if minutes == 1 else 's')) if minutes else None
	tokens.append('%d second%s'% (seconds, '' if seconds == 1 else 's')) if seconds else None
	if len(tokens):
		return (', ').join(tokens)
	else:
		return 'less than a second'

def human_readable_event(event):
	if event.reason == 'CHANGED':
		desc = 'Change level to ' + str(event.level)
	else:
		desc = event.reason
	delta = datetime.datetime.now() - dateutil.parser.parse(event.timestamp)
	return '%s at %s (%s ago)' % (desc, event.timestamp, human_readable_timedelta(delta))

def stash_house(theHouse):
	global house
	house = theHouse

	app.jinja_env.filters['order_device_states'] = house.order_device_states
	app.jinja_env.filters['order_device_types'] = house.order_device_types
	app.jinja_env.filters['human_readable_timedelta'] = human_readable_timedelta
	app.jinja_env.filters['human_readable_event'] = human_readable_event


def start(theHouse, port = None, public = False, webdebug = False):
	# save house object for handler classes to use
	if theHouse:
		stash_house(theHouse)

	# start webserver
	app_args = {}
	if port:
		app_args['port'] = port
	if public:
		app_args['host'] = '0.0.0.0'
	if webdebug:
		app_args['debug'] = True
	app.run(**app_args)
