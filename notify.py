# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of various home automation gateways.
#
# This module provides external notifications by email.
#
# BUGS: the smtplib calls in SgNotify.email() should be asynchronous,
# and not tie up the calling thread if smtplib takes a long time.

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
			self.smtp_ssl = config.email.get('use_ssl', False)
			self.smtp_auth = config.email.get('authenticate', None)

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
		if self.smtp_ssl:
			smtp = smtplib.SMTP_SSL(self.smtp_host)
		else:
			smtp = smtplib.SMTP(self.smtp_host)
		if self.smtp_auth:
			smtp.login(self.smtp_auth['username'], self.smtp_auth['password'])
		smtp.sendmail(self.smtp_sender, recipient, msg.as_string())


if __name__ == '__main__':
	import yaml
	import sg_util
	config = sg_util.AttrDict(yaml.safe_load(open('config.yaml')))
	notifyConfig = config.notifications
	notify = SgNotify(notifyConfig)
	sender = notifyConfig.email.sender

	print 'Notify test: using sender address %s' % sender

	# test email api directly (using the configured sender as recipient)
	assert notify.is_configured_for(notify.EMAIL)
	notify.email(sender, 'hello from SgNotify unit test')

	# test general api (assuming config.yaml has this alias)
	assert notify.can_notify('mv')
	notify.notify('mv', 'hello again from SgNotify unit test')
