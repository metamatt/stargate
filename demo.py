from flask import Flask, request, render_template, redirect, url_for

app = Flask(__name__)
house = None

@app.route('/')
def root_index():
	return '<a href=/demo/>Demo</a>'

@app.route('/demo/')
def demo_index():
	return render_template('index.html')

@app.route('/demo/list/<criteria>')
def demo_list(criteria):
	if criteria == 'on':
		outputs = house.get_on_devices()
	elif criteria == 'off':
		outputs = house.get_off_devices()
	elif criteria == 'all':
		outputs = house.get_all_devices()
	else:
		raise Exception('bad request')
	
	return render_template('outputList.html', outputs = outputs)

@app.route('/demo/get/<int:iid>')
def demo_get_output(iid):
	output = house.get_device_by_iid(iid)
	return render_template('outputList.html', outputs = [output])

@app.route('/demo/set/<int:iid>', methods = ['POST'])
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

def start(theHouse, debug = False):
	# save repeater for handler classes to use
	global house
	house = theHouse

	# start webserver
	if debug:
		app.debug = True
	app.run()
