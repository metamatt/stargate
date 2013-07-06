# (c) 2013 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system and friends.
#
# Threading module basically acts like Python one but dispatches exceptions
# to sys.excepthook instead of stderr.

import sys
import threading

Event = threading.Event
RLock = threading.RLock

class Thread(threading.Thread):
	# wrap start (which is normalling called on threading.Thread, not subclass)
	# to replace run method with our wrapper.
	def start(self, *args, **kwargs):
		subclass_run = self.run
		def run_and_catch(*args, **kwargs):
			try:
				subclass_run(*args, **kwargs)
			except:
				sys.excepthook(*sys.exc_info())
		self.run = run_and_catch

		super(Thread, self).start(*args, **kwargs)
