# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Control of Lutron RadioRa2 system and friends.
#
# Persistence module for tracking device state changes, history, statistics.
# Implemented atop SQLite3.
#
# Goal is to be able to provide data in forms like:
# _light_ _x_ is _on_ for _45 minutes_, _5_ changes today, on for _2 hours_ with an average level of _50%_.
# _door_ _x_ is _closed_ since _45 minutes_, _5_ changes today, open for _5 hours_ and closed for _12 hours).
# _device_ _name_ is _state_ since _changetime_, _numchanges_ in _timebucket_, _interesting_state_ for _time_in_state_ ...
#
# Bugs/work items:
# - last_tallied_ts may fit more naturally in the history bucket, not the device-status table?
# - not tracking average level while on yet (and might need more parameters/persisted fields to do so)
# - bucket rollover, not implemented yet
# - week bucket doesn't fit the design well


# A note on timekeeping: we want to know the last-changed time for each device, so we can say when it last changed and also
# calculate how much time it's spent in each state. However, when we aren't running, we might miss events, and there's no way
# to catch up with things we missed when we restart. So, we keep 2 timestamps: the last thing we saw (ever, including previous
# runs) and the last thing we saw while continuously watching. Device-state-change notifications update both; when we restart
# we update only the second one (so it follows that the current-run timestamp >= the any-run timestamp). Depending on the
# purpose, we access one or the other: deltas of time-in-state are always based only on authoritative data (the current-run
# timestamp); however device descriptions include a "last change we saw" field that is allowed to use previous-run data.
# Another corollary: we track on_time and off_time, but these might not add up to the entire tracked time window; any
# difference should be time we weren't running during which we can't say anything about the state.

import datetime
import dateutil.parser
import logging
import signal
import sqlite3
import sys
import threading
import time


logger = logging.getLogger(__name__)


class SgPersistence(object):
	def __init__(self, dbconfig):
		
		self._install_signal_handlers()
		self._dbfilename = dbconfig['datafile']
		self._conn = sqlite3.connect(self._dbfilename, check_same_thread = False)
		self._conn.row_factory = sqlite3.Row
		self._cursor = self._conn.cursor()
		self._version = 1
		self._init_schema()
		self._clear_transient_values()
		self._lock = threading.RLock()
		self._checkpoint_interval = float(dbconfig['checkpoint_interval'])
		if self._checkpoint_interval > 0:
			self._install_periodic_checkpointer()

	# public interface
	# XXX: should public methods work directly on sg_devid instead of (gateway_id, gateway_devid) pairs?
	def get_device_id(self, gateway_id, gateway_device_id):
		with self._lock:
			c = self._cursor
			c.execute('SELECT sg_device_id FROM device_map WHERE gateway_id=? AND gateway_device_id=?', (gateway_id, gateway_device_id))
			row = c.fetchone()
			if row:
				dev_id = row[0]
			else:
				c.execute('INSERT INTO device_map VALUES(?,?,NULL)', (gateway_id, gateway_device_id))
				dev_id = c.lastrowid
				self._commit()
			return dev_id
	
	def get_area_id(self, area_id):
		# XXX: we reuse and abuse the device_map table for areas as well; that's the easiest way to
		# get non-overlapping ids (which isn't strictly necessary but seems like good practice)
		return self.get_device_id('__area__', area_id)

	def init_device_state(self, gateway_id, gateway_device_id, state):
		# This is a way of updating the tables used by on_device_state_change for events missed when we weren't running
		with self._lock:
			c = self._cursor
			dev_id = self.get_device_id(gateway_id, gateway_device_id)
			current_ts = datetime.datetime.now()
			c.execute('INSERT OR REPLACE INTO device_status(sg_device_id, last_tallied_ts, last_state) VALUES(?,?,?)',
			           (dev_id, current_ts.isoformat(), state))
			self._commit()

	def on_device_state_change(self, gateway_id, gateway_device_id, state):
		# XXX TODO: handle partial-on states (on_details)
		with self._lock:
			dev_id = self.get_device_id(gateway_id, gateway_device_id)
			# query device previous state
			prev_state = self._get_device_prev_state(dev_id)
			# update last-change table
			delta, ts_current = self._get_device_timedelta(dev_id, 'last_tallied') # want to use current-run-only
			c = self._cursor
			c.execute('INSERT OR REPLACE INTO device_status(sg_device_id, last_seen_event_ts, last_state) VALUES(?,?,?)', (dev_id, ts_current.isoformat(), state))
			# update history bucket
			self._tally_device_state_history(dev_id, prev_state, delta, ts_current, True)
			# commit
			self._commit()

	def checkpoint_device_state(self, gateway_id, gateway_device_id):
		# This is a way of updating the tables used by on_device_state_change for time passing without changes while we are running
		with self._lock:
			dev_id = self.get_device_id(gateway_id, gateway_device_id)
			self._checkpoint_device_state(dev_id)
			# commit
			self._commit()

	def get_delta_since_change(self, gateway_id, gateway_device_id):
		# get time (in seconds) since device registered a change, or None if not known (not since startup)
		with self._lock:
			dev_id = self.get_device_id(gateway_id, gateway_device_id)
			delta, ts_current = self._get_device_timedelta(dev_id, 'last_seen_event') # allow timestamp reuse across restarts
			return delta
	
	def get_action_count(self, gateway_id, gateway_device_id, bucket):
		with self._lock:
			c = self._cursor
			dev_id = self.get_device_id(gateway_id, gateway_device_id)
			history = self._get_history_bucket(dev_id, bucket)
			return history['num_changes']
		
	def get_time_in_state(self, gateway_id, gateway_device_id, state, bucket):
		# state: boolean (anything evaluating true for on, false for off)
		with self._lock:
			c = self._cursor
			dev_id = self.get_device_id(gateway_id, gateway_device_id)
			# Find previous time-in-state (already billed and accounted in historical bucket table)
			history = self._get_history_bucket(dev_id, bucket)
			seconds_in_state = history['on_time' if state else 'off_time']
			# Add current time-in-state (historical time counts only up to the last change; add time from them till now if it's still in that state)
			c.execute('SELECT last_state FROM device_status WHERE sg_device_id = ?', (dev_id, ))
			row = c.fetchone()
			if row and row['last_state'] == state:
				delta, ts_current = self._get_device_timedelta(dev_id, 'last_tallied')
				seconds_in_state += delta.total_seconds()
			return datetime.timedelta(seconds = seconds_in_state)
		
	def get_bucket_name(self, bucket):
		# state: boolean (anything evaluating true for on, false for off)
			c = self._cursor
			c.execute('SELECT * FROM bucket_defs WHERE bucket_id = ?', (bucket,))
			row = c.fetchone()
			return row['bucket_name']

	# private helpers
	def _checkpoint_all(self):
		logger.warn('database checkpoint requested')
		with self._lock:
			c = self._cursor
			c.execute('SELECT sg_device_id FROM device_map')
			for row in c.fetchall():
				dev_id = row[0]
				self._checkpoint_device_state(dev_id)
			self._commit()

	def _checkpoint_device_state(self, dev_id):
		# Internal helper function: requires lock, does not commit; caller must take care of locking and committing
		assert self._lock._is_owned() # XXX I want a way to check if owned *by me*!
		# query device previous state
		prev_state = self._get_device_prev_state(dev_id)
		# get amount of untallied time
		delta, ts_current = self._get_device_timedelta(dev_id, 'last_tallied')
		# update history bucket
		self._tally_device_state_history(dev_id, prev_state, delta, ts_current, False)
		# note: no commit
		
	def _tally_device_state_history(self, dev_id, prev_state, delta, ts_current, changed):
		# Internal helper function: requires lock, does not commit; caller must take care of locking and committing
		assert self._lock._is_owned() # XXX I want a way to check if owned *by me*!
		# update history bucket
		time_in_prev_state = delta.total_seconds() if delta else 0
		history = self._get_history_bucket(dev_id, 1)
		on_time, off_time = (history['on_time'], history['off_time'])
		if prev_state == 0: # was off, tally some off_time
			logger.debug('adding %g sec to %g sec of off_time for did %d' % (time_in_prev_state, off_time, dev_id))
			off_time += time_in_prev_state
		elif prev_state > 0: # was on, tally some on_time
			logger.debug('adding %g sec to %g sec of on_time for did %d' % (time_in_prev_state, on_time, dev_id))
			on_time += time_in_prev_state
		else: # note that we ignore any changes from prev_state == -1
			logger.debug('ignoring %g sec in unknown state for did %d' % (time_in_prev_state, dev_id))
		num_changes = history['num_changes']
		if changed:
			num_changes += 1
		c = self._cursor
		c.execute('INSERT OR REPLACE INTO change_history_buckets(sg_device_id, bucket_id, num_changes, on_time, off_time) VALUES(?,?,?,?,?)',
		          (dev_id, 1, num_changes, on_time, off_time))
		# update last-tallied time in device-state table
		c.execute('UPDATE device_status SET last_tallied_ts = ? WHERE sg_device_id = ?', (ts_current, dev_id))
		# note: no commit
		
	def _get_device_prev_state(self, dev_id):
		assert self._lock._is_owned() # XXX I want a way to check if owned *by me*!
		c = self._cursor
		c.execute('SELECT last_state FROM device_status WHERE sg_device_id = ?', (dev_id, ))
		row = c.fetchone()
		if row:
			prev_state = row['last_state']
		else:
			prev_state = -1
		return prev_state

	def _commit(self):
		self._conn.commit()

	def _ts_from_string(self, ts_string):
		return dateutil.parser.parse(ts_string)

	def _get_device_timedelta(self, device_id, column_name_base):
		# Returns tuple: delta since last change to device, and 'now' value used in that calculation, useful for atomicity
		current_ts = datetime.datetime.now()
		c = self._cursor
		ts_column = column_name_base + '_ts'
		c.execute('SELECT %s FROM device_status WHERE sg_device_id = ?' % ts_column, (device_id, )) # verified-safe use of % string replacement in SQL query
		row = c.fetchone()
		if row and row[0]:
			delta = current_ts - self._ts_from_string(row[0])
		else: # treat row with NULL value same as empty row, and start from now (nothing known about prior state, so no time elapsed in prior state)
			delta = None
		return (delta, current_ts)

	def _get_history_bucket(self, device_id, bucket):
		# Return (at least) a dict with num_changes, on_time and off_time.
		# This might be a row from the db if it exists, or a dict object mapping everything to 0 otherwise.
		c = self._cursor
		c.execute('SELECT * FROM change_history_buckets WHERE sg_device_id = ? AND bucket_id = ?', (device_id, bucket))
		history = c.fetchone()
		if not history: # create a fake "row" object usable as a dictionary with the values we care about
			history = { 'num_changes': 0, 'on_time': 0, 'off_time': 0 }
		return history

	def _init_schema(self):
		c = self._cursor
		# check whether schema has already been populated
		c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_version'")
		schema_exists = c.fetchone()[0]
		logger.debug('init_schema: detected %d existing schema' % schema_exists)
		if schema_exists > 0:
			# schema has been populated; make sure it's the same version we expect
			c.execute("SELECT version FROM schema_version WHERE object='stargate'")
			schema_version = c.fetchone()[0]
			# upgrade as necessary
			logger.debug('init_schema: runtime version %d, persisted version %d' % (self._version, schema_version))
			if schema_version != self._version:
				logger.debug('init_schema: will reuse existing tables after upgrade')
				self._upgrade_schema(schema_version)
			else:
				logger.debug('init_schema: reusing existing tables')
			# but no table-creation work to do
		else:
			logger.debug('init_schema: creating tables')
			self._create_schema()
			
	def _clear_transient_values(self):
		# Clear out fields which are not intended to persist beyond the lifetime of a single process.
		# (XXX: arguably such stuff should live only in the object model and not in the persistence layer....)
		c = self._cursor
		c.execute('UPDATE device_status SET last_tallied_ts = NULL, last_state = -1')
		self._commit()

	def _create_schema(self):
		c = self._cursor
		sql_cmds = '''
		-- version the schema itself
		CREATE TABLE schema_version (object STRING PRIMARY KEY, version INTEGER NOT NULL);
		INSERT INTO schema_version VALUES('stargate', %d);

		-- map from IDs used by rest of Stargate (gateway name, and id relative only to that gateway) to unique integer 'sg_device_id' used by following tables
		CREATE TABLE device_map (gateway_id STRING NOT NULL, gateway_device_id STRING NOT NULL, sg_device_id INTEGER PRIMARY KEY AUTOINCREMENT);
		CREATE INDEX device_map_index ON device_map(gateway_id, gateway_device_id);

		-- device status for time-in-state tracking
		-- last_seen_event_ts: last time we saw device change (persists across restart, there may have been newer changes we didn't see) -- useful to say 'last known event''
		-- last_tallied_ts: last time we tallied current state (this table) into history buckets (change_history_buckets table) -- reset at process start, so authoritative
		-- last_state: last known device state, this run only (state as of the last change)
		CREATE TABLE device_status (sg_device_id INTEGER PRIMARY KEY, last_seen_event_ts STRING, last_tallied_ts STRING, last_state INTEGER,
		                            FOREIGN KEY(sg_device_id) REFERENCES device_map(sg_device_id));

		-- history buckets
		CREATE TABLE bucket_defs (bucket_id INTEGER, bucket_name STRING, bucket_description STRING);
		INSERT INTO bucket_defs VALUES(1, 'day', 'today');
		INSERT INTO bucket_defs VALUES(2, 'month', 'this month');
		INSERT INTO bucket_defs VALUES(3, 'year', 'this year');
		INSERT INTO bucket_defs VALUES(4, 'lifetime', 'since installation');

		-- history counters, per device, per bucket
		CREATE TABLE change_history_buckets (sg_device_id INTEGER, bucket_id INTEGER, num_changes INTEGER, on_time INTEGER, on_details INTEGER, off_time INTEGER,
		                                     PRIMARY KEY(sg_device_id, bucket_id), FOREIGN KEY(sg_device_id) REFERENCES device_map(sg_device_id),
		                                     FOREIGN KEY(bucket_id) REFERENCES bucket_defs(bucket_id));
		''' % self._version # Yes, in general we should use db's ? string-formatting and not python's %, but this use is safe since we control the value of self.version
		c.executescript(sql_cmds)
		self._commit()

	def _upgrade_schema(self, from_version):
		if from_version > self._version:
			raise Exception('database version is from the future! (newer than runtime version)')
		raise Exception('db upgrade not implemented')

	def _install_signal_handlers(self):
		def handle_signal(signum, stack_frame):
			logger.warn("Received signal %d" % signum)
			self._checkpoint_all()
			if signum != signal.SIGHUP:
				logger.warn("Exiting on signal %d" % signum)
				sys.exit()

		signal.signal(signal.SIGINT, handle_signal)
		signal.signal(signal.SIGHUP, handle_signal)
		signal.signal(signal.SIGTERM, handle_signal)
	
	def _install_periodic_checkpointer(self):
		def checkpoint_callback(self):
			# invoke the checkpoint
			self._checkpoint_all()
			# and reinstall this one-shot timer
			self._install_periodic_checkpointer()
		self._checkpoint_thread = threading.Timer(self._checkpoint_interval, checkpoint_callback, args = [self])
		self._checkpoint_thread.setDaemon(True)
		self._checkpoint_thread.setName('db_cp_timer')
		self._checkpoint_thread.start()


# simple unit test
def main():
	logging.basicConfig(level = logging.DEBUG)
	dbconfig = { 'datafile': 'foo.sqlite', 'checkpoint_interval': 1 }
	p = SgPersistence(dbconfig)
	id = p.get_device_id('lutron', '24')
	print id
	id = p.get_device_id('lutron', '24')
	print id
	id = p.get_device_id('lutron', '35')
	print id
	id = p.get_device_id('dsc', '35')
	print id
	id = p.get_device_id('lutron', '24')
	print id
	id = p.get_device_id('lutron', '24')
	print id
	p.init_device_state('lutron', '24', 0)
	time.sleep(0.777) # off time
	p.on_device_state_change('lutron', '24', 1)
	time.sleep(3.5) # on time
	p.on_device_state_change('lutron', '24', 0)
	time.sleep(1.54) # off time
	p.on_device_state_change('lutron', '24', 1)
	return p

if __name__ == '__main__':
	main()
