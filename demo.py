from flask import Flask, request, render_template

app = Flask(__name__)
repeater = None

@app.route('/')
def root_index():
	return '<a href=/demo/>Demo</a>'

@app.route('/demo/')
def demo_index():
	return render_template('index.html')

@app.route('/demo/list/<criteria>')
def demo_list(criteria):
	if criteria == 'on':
		outputs = repeater.get_outputs_on()
	elif criteria == 'off':
		outputs = repeater.get_outputs_off()
	elif criteria == 'all':
		outputs = repeater.get_outputs_all()
	else:
		raise Exception('bad request')
	
	return render_template('outputList.html', outputs = outputs)

@app.route('/demo/get/<iid>')
def demo_get_output(iid):
	level = repeater.get_output_level(iid)
	output = repeater.layout.outputs[iid]
	return render_template('outputList.html', outputs = [(output, level)])

@app.route('/demo/set/<int:iid>', methods = ['POST'])
def demo_set_output(iid):
	params = request.form
	return 'TODO: Set %s to %s' % (iid, params['level'])


def start(withRepeater, debug = False):
	# save repeater for handler classes to use
	global repeater
	repeater = withRepeater

	# start webserver
	if debug:
		app.debug = True
	app.run()
