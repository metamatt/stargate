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
	EMAIL = 'email'

	def __init__(self, config):
		self.smtp_host = None
		self.smtp_sender = None
		self.aliases = config.recipients

		if config.has_key('email'):
			self.smtp_host = config.email.smtp_host
			self.smtp_sender = config.email.sender

	def notify(self, alias, message, subject = None):
		if not self.aliases.has_key(alias):
			logger.error('No notify alias configured for %s' % alias)
			return False
		for (method, address) in self.aliases[alias]:
			if method == SgNotify.EMAIL:
				self.email(address, message, subject)
			else:
				logger.error('No notify handler configured for method %s' % method)

	def can_notify(self, alias):
		if not self.aliases.has_key(alias):
			logger.error('No notify alias configured for %s' % alias)
			return False
		for (method, address) in self.aliases[alias]:
			if not self.is_configured_for(method):
				return False
		return True

	def is_configured_for(self, method):
		if method == SgNotify.EMAIL:
			return self.smtp_host is not None and self.smtp_sender is not None
		print 'bad method'
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

	# test email api directly
	assert notify.is_configured_for(notify.EMAIL)
	notify.email('matt@ginzton.net', 'hello from SgNotify unit test')

	# test general api (assuming config.yaml has this alias)
	assert notify.can_notify('mv')
	notify.notify('mv', 'hello again from SgNotify unit test')
