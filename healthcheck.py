# (c) 2018 Matt Ginzton, matt@ginzton.net
#
# Simple healthcheck for Stargate.

from flask import Flask
import logging
import threading


app = Flask(__name__)
state = {}
state['response'] = 'ok' # can be overridden in start()

@app.route('/')
def root():
    return state['response'] + '\n'

class HealthCheckThread(threading.Thread):
    def __init__(self, port):
        super(HealthCheckThread, self).__init__(name = 'healthcheck')
        self.daemon = True
        self.port = port
        self.logger = logging.getLogger('healthcheck')

    def run(self):
        self.logger.info('%s: serving healthcheck on port %d' % (self.logger.name, self.port))
        app.run(port = self.port, host = '0.0.0.0')

def start(port, response = ''):
    if response:
        state['response'] = response;
    hcThread = HealthCheckThread(port)
    hcThread.start()
