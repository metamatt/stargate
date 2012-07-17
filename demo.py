import time

from flask import Flask, request, render_template, redirect, url_for

import ra_house

app = Flask(__name__)
house = None

def order_device_states(states, devclass = 'device'):
	if devclass == 'output':
		return ra_house.OutputDevice.order_states(states)
	elif devclass == 'control':
		return ra_house.ControlDevice.order_states(states)
	else:
		return ra_house.LutronDevice.order_states(states)
app.jinja_env.filters['order_device_states'] = order_device_states


@app.route('/')
def root():
	return render_template('index.html')

@app.route('/controls/', defaults = {'filterlist': 'all'})
@app.route('/controls/<filterlist>')
def enumerate_controls(filterlist):
	filters = filterlist.split(',')
	controls = house.get_devices_filtered_by(filters, devclass = 'control')
	return render_template('outputList.html', devices = controls, devclass = 'control', active_filters = filters)

@app.route('/control/<int:iid>', methods = ['POST'])
def activate_control(iid):
	params = request.form
	button_id = params['button_id']
	action = params['action']
	control = house.get_device_by_iid(iid)
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
	return redirect(url_for('get_control', iid = iid))

@app.route('/control/<int:iid>/button/<int:button_id>/<action>')
def activate_control_hack(iid, button_id, action):
	control = house.get_device_by_iid(iid)
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
	return redirect(url_for('get_control', iid = iid))

@app.route('/outputs/', defaults = {'filterlist': 'all'})
@app.route('/outputs/<filterlist>')
def enumerate_outputs(filterlist):
	filters = filterlist.split(',')
	outputs = house.get_devices_filtered_by(filters, devclass = 'output')
	return render_template('outputList.html', devices = outputs, devclass = 'output', active_filters = filters)

# XXX should share code between these, type check, redirect to canonical url?
@app.route('/control/<int:iid>')
def get_control(iid):
	# XXX should type check? share code?
	control = house.get_device_by_iid(iid)
	return render_template('output.html', device = control, devclass = 'control')

@app.route('/device/<int:iid>')
def get_device(iid):
	device = house.get_device_by_iid(iid)
	# XXX should type check and redirect?
	return render_template('output.html', device = device, devclass = 'device')

@app.route('/output/<int:iid>')
def get_output(iid):
	# XXX should type check? share code?
	output = house.get_device_by_iid(iid)
	return render_template('output.html', device = output, devclass = 'output')

@app.route('/output/<int:iid>', methods = ['POST'])
def set_output(iid):
	params = request.form
	output = house.get_device_by_iid(iid)
	state = params['state']
	if state == 'level':
		level = float(params['level'])
		output.set_level(level)
	else:
		output.go_to_state(state)
	# XXX should make this respond to async operation when it completes; for now just wait a bit
	# and show the device details page
	time.sleep(0.3)
	return redirect(url_for('get_output', iid = iid))

@app.route('/output/multi/to_state', methods = ['POST'])
def set_outputs_to_state():
	params = request.form
	state = params['state']
	iids = map(int, params['outputs'].split(','))
	for iid in iids:
		output = house.get_device_by_iid(iid)
		output.go_to_state(state)
	# XXX should make this respond to async operation when it completes; for now just wait a bit
	# hack: show the page for the outputs in the area containing the last device, filtered by device type
	time.sleep(0.2 * len(iids))
	return redirect(url_for('enumerate_outputs_by_area', iid = output.area.iid, filterlist = output.devtype))

@app.route('/areas/', defaults = {'filterlist': 'all'})
@app.route('/areas/<filterlist>')
def enumerate_areas(filterlist):
	filters = filterlist.split(',')
	areas = house.get_areas_filtered_by(filters)
	return render_template('areaList.html', areas = areas, active_filters = filters)

@app.route('/area/<int:iid>/outputs/', defaults = {'filterlist': 'all'})
@app.route('/area/<int:iid>/outputs/<filterlist>')
def enumerate_outputs_by_area(iid, filterlist):
	area = house.get_devicearea_by_iid(iid)
	filters = filterlist.split(',')
	outputs = area.get_devices_filtered_by(filters, devclass = 'output')
	return render_template('outputList.html', area_filter = area, devices = outputs, devclass = 'output', active_filters = filters)

@app.route('/area/<int:iid>/controls/', defaults = {'filterlist': 'all'})
@app.route('/area/<int:iid>/outputs/<filterlist>')
def enumerate_controls_by_area(iid, filterlist):
	area = house.get_devicearea_by_iid(iid)
	filters = filterlist.split(',')
	controls = area.get_devices_filtered_by(filters, devclass = 'control')
	return render_template('outputList.html', area_filter = area, devices = controls, devclass = 'control', active_filters = filters)

@app.route('/area/<int:iid>/devices/', defaults = {'filterlist': 'all'})
@app.route('/area/<int:iid>/devices/<filterlist>')
def enumerate_devices_by_area(iid, filterlist):
	area = house.get_devicearea_by_iid(iid)
	filters = filterlist.split(',')
	devices = area.get_devices_filtered_by(filters)
	return render_template('outputList.html', area_filter = area, devices = devices, devclass = 'device', active_filters = filters)

@app.context_processor
def inject_house():
	return dict(house = house)

def start(theHouse, debug = False):
	# save repeater for handler classes to use
	global house
	house = theHouse

	# start webserver
	if debug:
		app.debug = True
	app.run()
