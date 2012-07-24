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
# - not currently passing in state, but need it for time_in_state
# - dubiously necessary to throw away last-change-time on restart to avoid using it in transition calculation; should separate this? (related: periodic checkpoints will need similar difference between last-checkpointed time and last-changed time)
# - not tracking average level while on yet (and might need more parameters/persisted fields to do so)
# - bucket rollover, not implemented yet
# - week bucket doesn't fit the design well


import datetime
import dateutil.parser
import logging
import sqlite3
import time


logger = logging.getLogger(__name__)


class SgPersistence(object):
	def __init__(self, dbfilename):
		self._dbfilename = dbfilename
		self._conn = sqlite3.connect(dbfilename, check_same_thread = False) # XXX is this safe now?
		self._conn.row_factory = sqlite3.Row
		self._cursor = self._conn.cursor()
		self._version = 1
		self._init_schema()

	# public interface
	def get_device_id(self, host_system_id, host_device_id):
		c = self._cursor
		c.execute('SELECT sg_device_id FROM device_map WHERE host_system_id=? AND host_device_id=?;', (host_system_id, host_device_id))
		row = c.fetchone()
		if row:
			result = row[0]
		else:
			c.execute('INSERT INTO device_map VALUES(?,?,NULL)', (host_system_id, host_device_id))
			result = c.lastrowid
			self.commit()
		return result
		
	def on_device_state_change(self, host_system_id, host_device_id, state):
		# XXX TODO: handle partial-on states (on_details)
		c = self._cursor
		id = self.get_device_id(host_system_id, host_device_id)
		# update last-change table
		(delta, ts_current) = self._get_device_change_delta_until(id)
		time_in_prev_state = delta.total_seconds() if delta else 0
		c.execute('INSERT OR REPLACE INTO last_change VALUES(?,?)', (id, ts_current.isoformat()))
		# update history bucket
		history = self._get_history_bucket(id, 1)
		if state: # from off to on
			logger.debug('adding %g to %g of off_time for did %d' % (time_in_prev_state, history['off_time'], id))
			off_time = history['off_time'] + time_in_prev_state
			on_time = history['on_time']
		else: # from on to off
			logger.debug('adding %g to %g of on_time for did %d' % (time_in_prev_state, history['on_time'], id))
			off_time = history['off_time']
			on_time = history['on_time'] + time_in_prev_state
		num_changes = history['num_changes'] + 1
		c.execute('INSERT OR REPLACE INTO change_history_buckets(sg_device_id, bucket_id, num_changes, on_time, off_time) VALUES(?,?,?,?,?)',
		          (id, 1, num_changes, on_time, off_time))
		# commit
		self.commit()
		
	def fastforward_device_state(self, host_system_id, host_device_id):
		# This is a way of updating the tables used by on_device_state_change for events missed when we weren't running
		c = self._cursor
		id = self.get_device_id(host_system_id, host_device_id)
		c.execute('INSERT OR REPLACE INTO last_change VALUES(?,NULL)', (id, ))
		self.commit()
	
	def checkpoint_device_state(self, host_system_id, host_device_id):
		# This is a way of updating the tables used by on_device_state_change for time passing without changes while we are running
		# XXX TODO, along with bucket rollover
		pass
		
	def get_delta_since_change(self, host_system_id, host_device_id):
		# get time (in seconds) since device registered a change, or None if not known (not since startup)
		id = self.get_device_id(host_system_id, host_device_id)
		(delta, ts_current) = self._get_device_change_delta_until(id)
		return delta
	
	def get_action_count(self, host_system_id, host_device_id, bucket):
		c = self._cursor
		id = self.get_device_id(host_system_id, host_device_id)
		history = self._get_history_bucket(id, bucket)
		return history['num_changes']
		
	def get_time_in_state(self, host_system_id, host_device_id, state, bucket):
		# state: boolean (anything evaluating true for on, false for off)
		c = self._cursor
		id = self.get_device_id(host_system_id, host_device_id)
		history = self._get_history_bucket(id, bucket)
		return history['on_time' if state else 'off_time']
		# XXX this counts only up to the last change; we should add time from then till now if it's still in that state.
		# So I guess this layer should know current state, and just not consider it authoritative?
		
	def get_bucket_name(self, bucket):
		c = self._cursor
		c.execute('SELECT * FROM bucket_defs WHERE bucket_id = ?;', (bucket,))
		row = c.fetchone()
		return row['bucket_name']

	def commit(self):
		self._conn.commit()

	# private helpers
	def _ts_from_string(self, ts_string):
		return dateutil.parser.parse(ts_string)

	def _get_device_change_delta_until(self, device_id):
		# returns tuple: delta since last change to device, and 'now' value used in that calculation, useful for atomicity
		current_ts = datetime.datetime.now()
		c = self._cursor
		c.execute('SELECT timestamp FROM last_change WHERE sg_device_id = ?', (device_id,))
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
		c.execute('SELECT * FROM change_history_buckets WHERE sg_device_id = ? AND bucket_id = ?;', (device_id, bucket))
		history = c.fetchone()
		if not history: # create a fake "row" object usable as a dictionary with the values we care about
			history = { 'num_changes': 0, 'on_time': 0, 'off_time': 0 }
		return history

	def _init_schema(self):
		c = self._cursor
		# check whether schema has already been populated
		c.execute('''SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_version';''')
		schema_exists = c.fetchone()[0]
		logger.debug('init_schema: detected %d existing schema' % schema_exists)
		if schema_exists > 0:
			# schema has been populated; make sure it's the same version we expect
			c.execute('''SELECT version FROM schema_version WHERE object='stargate';''')
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

	def _create_schema(self):
		c = self._cursor
		sql_cmds = '''
		CREATE TABLE schema_version (object STRING PRIMARY KEY, version INTEGER NOT NULL);
		INSERT INTO schema_version VALUES('stargate', %d);

		CREATE TABLE device_map (host_system_id STRING NOT NULL, host_device_id STRING NOT NULL, sg_device_id INTEGER PRIMARY KEY AUTOINCREMENT);
		CREATE INDEX device_map_index ON device_map(host_system_id, host_device_id);

		CREATE TABLE last_change (sg_device_id INTEGER PRIMARY KEY, timestamp STRING, FOREIGN KEY(sg_device_id) REFERENCES device_map(sg_device_id));

		CREATE TABLE change_history_buckets (sg_device_id INTEGER, bucket_id INTEGER, num_changes INTEGER, on_time INTEGER, on_details INTEGER, off_time INTEGER,
		                                     PRIMARY KEY(sg_device_id, bucket_id), FOREIGN KEY(sg_device_id) REFERENCES device_map(sg_device_id));

		CREATE TABLE bucket_defs (bucket_id INTEGER, bucket_name STRING, bucket_description STRING);
		INSERT INTO bucket_defs VALUES(1, 'day', 'today');
		INSERT INTO bucket_defs VALUES(2, 'month', 'this month');
		INSERT INTO bucket_defs VALUES(3, 'year', 'this year');
		INSERT INTO bucket_defs VALUES(4, 'lifetime', 'since installation);
		''' % self._version # Yes, in general we should use db's ? string-formatting and not python's %, but this use is safe since we control the value of self.version
		c.executescript(sql_cmds)
		self.commit()

	def _upgrade_schema(self, from_version):
		if from_version > self._version:
			raise Exception('database version is from the future! (newer than runtime version)')
		raise Exception('db upgrade not implemented')


# simple unit test
def main():
	logging.basicConfig(level = logging.DEBUG)
	p = SgPersistence('foo.sqlite')
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
	p.fastforward_device_state('lutron', '24', 0)
	time.sleep(0.777) # untracked time
	p.on_device_state_change('lutron', '24', 1)
	time.sleep(3.5) # on time
	p.on_device_state_change('lutron', '24', 0)
	time.sleep(1.54) # off time
	p.on_device_state_change('lutron', '24', 1)
	return p

if __name__ == '__main__':
	main()
