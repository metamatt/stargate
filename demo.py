from flask import Flask, request, render_template, redirect, url_for
from ra_house import OutputDevice
import time

app = Flask(__name__)
house = None

app.jinja_env.filters['order_states'] = OutputDevice.order_states

@app.route('/')
def root():
	return render_template('index.html')

@app.route('/outputs/', defaults = {'filterlist': 'all'})
@app.route('/outputs/<filterlist>')
def enumerate_outputs(filterlist):
	filters = filterlist.split(',')
	outputs = house.get_devices_filtered_by(filters)
	return render_template('outputList.html', outputs = outputs, active_filters = filters)

@app.route('/output/<int:iid>')
def get_output(iid):
	output = house.get_device_by_iid(iid)
	return render_template('output.html', output = output)

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
	# hack: show the page for the area containing the last device, filtered by device type
	time.sleep(0.2 * len(iids))
	return redirect(url_for('enumerate_outputs_by_area', iid = output.area.iid, filterlist = output.type))

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
	outputs = area.get_devices_filtered_by(filters)
	return render_template('outputList.html', area_filter = area, outputs = outputs, active_filters = filters)

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
