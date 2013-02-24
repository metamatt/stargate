# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides external notifications by email.

import logging
import smtplib
from email.mime.text import MIMEText


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))


class SgNotify(object):
	# supported notification methods
	EMAIL = 1

	def __init__(self, config):
		self.smtp_host = None
		self.smtp_sender = None

		if config.has_key('email'):
			self.smtp_host = config.email.smtp_host
			self.smtp_sender = config.email.sender

	def is_configured_for(self, method):
		if method == SgNotify.EMAIL:
			return self.smtp_host is not None and self.smtp_sender is not None
		return False

	def email(self, recipient, message, subject = None):
		msg = MIMEText(message)
		msg['Subject'] = subject or 'Stargate'
		msg['From'] = self.smtp_sender
		msg['To'] = recipient
		smtp = smtplib.SMTP(self.smtp_host)
		smtp.sendmail(self.smtp_sender, recipient, msg.as_string())


if __name__ == '__main__':
	import yaml
	import sg_util
	config = sg_util.AttrDict(yaml.safe_load(open('config.yaml')))
	notify = SgNotify(config['notifications'])
	assert notify.is_configured_for(notify.EMAIL)
	notify.email('matt@ginzton.net', 'hello from SgNotify unit test')
