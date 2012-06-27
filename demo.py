from flask import Flask, request, render_template, redirect, url_for
from ra_house import Device

app = Flask(__name__)
house = None

@app.route('/')
def root_index():
	return '<a href=/demo/>Demo</a>'

@app.route('/demo/')
def demo_index():
	return render_template('index.html')

@app.route('/output/list/', defaults = {'filterlist': 'all'})
@app.route('/output/list/<filterlist>')
def list_outputs(filterlist):
	filters = filterlist.split(',')
	outputs = house.get_devices_filtered_by(filters)
	return render_template('outputList.html', outputs = outputs, active_filters = filters)

@app.route('/output/get/<int:iid>')
def demo_get_output(iid):
	output = house.get_device_by_iid(iid)
	return render_template('outputList.html', outputs = [output])

@app.route('/output/set/<int:iid>', methods = ['POST'])
def demo_set_output(iid):
	params = request.form
	output = house.get_device_by_iid(iid)
	level = float(params['level'])
	#return 'TODO: Set %s to %s' % (iid, level)
	output.set_level(level)
	# XXX should make this respond to async operation when it completes; for now just wait a bit
	import time
	time.sleep(0.3)
	return redirect(url_for('demo_get_output', iid = iid))

@app.route('/area/list/', defaults = {'filterlist': 'all'})
@app.route('/area/list/<filterlist>')
def list_areas(filterlist):
	filters = filterlist.split(',')
	areas = house.get_areas_filtered_by(filters)
	return render_template('areaList.html', areas = areas, active_filters = filters)

@app.route('/area/<int:iid>/', defaults = {'filterlist': 'all'})
@app.route('/area/<int:iid>/<filterlist>')
def enumerate_area(iid, filterlist):
	area = house.get_devicezone_by_iid(iid)
	filters = filterlist.split(',')
	outputs = area.get_devices_filtered_by(filters)
	return render_template('outputList.html', area = area, outputs = outputs)

@app.context_processor
def inject_device_filters():
	return dict(all_filters = Device.FILTERS)

def start(theHouse, debug = False):
	# save repeater for handler classes to use
	global house
	house = theHouse

	# start webserver
	if debug:
		app.debug = True
	app.run()
