from flask import Flask, request, render_template, redirect, url_for
from ra_house import Device

app = Flask(__name__)
house = None

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
	level = float(params['level'])
	#return 'TODO: Set %s to %s' % (iid, level)
	output.set_level(level)
	# XXX should make this respond to async operation when it completes; for now just wait a bit
	import time
	time.sleep(0.3)
	return redirect(url_for('get_output', iid = iid))

@app.route('/areas/', defaults = {'filterlist': 'all'})
@app.route('/areas/<filterlist>')
def enumerate_areas(filterlist):
	filters = filterlist.split(',')
	areas = house.get_areas_filtered_by(filters)
	return render_template('areaList.html', areas = areas, active_filters = filters)

@app.route('/area/<int:iid>/outputs/', defaults = {'filterlist': 'all'})
@app.route('/area/<int:iid>/outputs/<filterlist>')
def enumerate_outputs_by_area(iid, filterlist):
	area = house.get_devicezone_by_iid(iid)
	filters = filterlist.split(',')
	outputs = area.get_devices_filtered_by(filters)
	return render_template('outputList.html', area = area, outputs = outputs, active_filters = filters)

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
