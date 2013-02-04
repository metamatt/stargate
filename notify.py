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
	def __init__(self, config):
		self.smtp_host = config.smtp_host
		self.smtp_sender = config.smtp_sender
		self.smtp = smtplib.SMTP(self.smtp_host)

	def email(self, recipient, message, subject = None):
		msg = MIMEText(message)
		msg['Subject'] = subject or 'Stargate'
		msg['From'] = self.smtp_sender
		msg['To'] = recipient
		self.smtp.sendmail(self.smtp_sender, recipient, msg.as_string())


if __name__ == '__main__':
	import yaml
	import sg_util
	config = sg_util.AttrDict(yaml.safe_load(open('config.yaml')))
	notify = SgNotify(config['notifications'])
	notify.email('matt@ginzton.net', 'hello from SgNotify unit test')
