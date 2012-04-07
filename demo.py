import web

urls = (
	'/', 'RootIndex',
	'/demo', 'DemoIndex',
	'/demo/', 'DemoIndex',
	'/demo/list/(.*)', 'DemoList',
	'/demo/get/(.*)', 'DemoGetOutput',
	'/demo/set/(.*)', 'DemoSetOutput'
)
repeater = None
templates = web.template.render('demo/')

class RootIndex:
	def GET(self):
		return '<a href=/demo/>Demo</a>'

class DemoIndex:
	def GET(self):
		return templates.index()

class DemoList:
	def GET(self, param):
		if param == 'on':
			outputs = repeater.get_outputs_on()
		elif param == 'off':
			outputs = repeater.get_outputs_off()
		elif param == 'all':
			outputs = repeater.get_outputs_all()
		else:
			raise Exception('bad request')
		
		# format each list item, and jam these together with unicode string concat
		items = unicode()
		# each member of the output list is a 2-tuple with name, level
		for (output, level) in outputs:
			item = templates.oneOutput(output, level)
			items = items + unicode(item)
		# then we dump these into the list template, which allows raw html injection
		return templates.list(items)

class DemoGetOutput:
	def GET(self, iid):
		level = repeater.get_output_level(iid)
		output = repeater.layout.outputs[iid]
		item = templates.oneOutput(output, level)
		return templates.list(item)
	
class DemoSetOutput:
	def POST(self, iid):
		params = web.input()
		return 'TODO: Set %s to %s' % (iid, params.level)

app = web.application(urls, globals())

def start(withRepeater):
	# save repeater for handler classes to use
	global repeater
	repeater = withRepeater

	# XXX clobber argv because web.py thinks it knows how to parse it. Nuh-uh.
	import sys
	sys.argv = []

	# start webserver
	app.run()
