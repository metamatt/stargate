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
# - not tracking average level while on yet (and might need more parameters/persisted fields to do so)
# - should cap the amount of data we store, and aggregate into less granular buckets
#
# A note on timekeeping: we write an event whenever a device changes state, and assuming we were running and watching
# the whole time, we know what state that device was in for the entire interval between the previous and current events
# for that device. However, if we crash or get killed or lose the connection to a device's gateway, we won't be able to
# track it until we restart. To represent this, there are two additional event types: "checkpoint" (meaning nothing's
# changed since the last event) and "startup" (meaning we don't know what happened since the last event). An interval
# ending in a startup event is mapped to unknown state for that device, and checkpoints establish an upper bound on how
# long such intervals can be.

import datetime
import dateutil.parser
import logging
import signal
import sqlite3
import sys
import threading
import time

from sg_util import AttrDict


logger = logging.getLogger(__name__)
logger.info('%s: init with level %s' % (logger.name, logging.getLevelName(logger.level)))

AREA_MAGIC_GATEWAY_ID = '__area__'

class EventCode(object):
	CHANGED = 1    # changed since last
	CHECKPOINT = 2 # unchanged since last
	RESTART = 3    # unknown since last

	@classmethod
	def from_int(cls, i):
		return [ 'CHANGED', 'CHECKPOINT', 'RESTART' ][i - 1];


class SgPersistence(object):
	def __init__(self, dbconfig):
		self._install_signal_handlers()
		self._dbfilename = dbconfig.datafile
		self._conn = sqlite3.connect(self._dbfilename, check_same_thread = False)
		self._conn.row_factory = sqlite3.Row
		self._cursor = self._conn.cursor()
		self._version = 1
		self._init_schema()
		self._lock = threading.RLock()
		self._checkpoint_interval = float(dbconfig.checkpoint_interval)
		if self._checkpoint_interval > 0:
			self._install_periodic_checkpointer()

	# public interface
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
		return self.get_device_id(AREA_MAGIC_GATEWAY_ID, area_id)

	def record_startup(self, dev_id, level):
		with self._lock:
			c = self._cursor
			current_ts = datetime.datetime.now().isoformat()
			c.execute('INSERT INTO device_events(sg_device_id, event_code, level, event_ts) VALUES(?,?,?,?)',
				(dev_id, EventCode.RESTART, level, current_ts))
			self._commit()

	def record_change(self, dev_id, level):
		with self._lock:
			c = self._cursor
			self._save_newest_knowledge(dev_id, EventCode.CHANGED, level)
			self._commit()

	def get_delta_since_change(self, dev_id):
		# get time (in seconds) since device registered a change, or None if not known (not since startup)
		with self._lock:
			c = self._cursor
			# get newest event for device, ignoring checkpoint events.
			c.execute('SELECT event_ts, event_code FROM device_events WHERE sg_device_id = ? AND event_code <> ? ORDER BY event_ts DESC LIMIT 1',
				(dev_id, EventCode.CHECKPOINT))
			row = c.fetchone()
			if row is None:
				logger.warn('No events for device %s' % dev_id)
				return None
			# if newest is a change event, we can calculate delta. If it's a restart event, we cannot.
			if row['event_code'] == EventCode.CHANGED:
				then = self._ts_from_string(row['event_ts'])
				return datetime.datetime.now() - then
			else:
				return None

	def get_action_count(self, dev_id, age_limit = None):
		with self._lock:
			c = self._cursor
			start_time = (datetime.datetime.now() - age_limit).isoformat() if age_limit is not None else '0'
			c.execute('SELECT COUNT(*) FROM device_events WHERE sg_device_id = ? AND event_code = ? AND event_ts > ?',
				(dev_id, EventCode.CHANGED, start_time))
			return c.fetchone()[0]

	def get_time_in_state(self, dev_id, state):
		# state: boolean (anything evaluating true for on, false for off)
		delta = datetime.timedelta()
		with self._lock:
			c = self._cursor
			# Iterate entire device history, looking at transitions where we know the state on both sides
			# That is, from (changed or restart) to (changed or checkpoint).
			c.execute('SELECT event_ts, event_code, level FROM device_events WHERE sg_device_id = ? ORDER BY event_ts ASC', (dev_id, ))
			prev_code = None
			prev_ts = None
			prev_level = None
			for row in c:
				cur_code = row['event_code']
				cur_ts = self._ts_from_string(row['event_ts'])
				if prev_code == EventCode.CHANGED or prev_code == EventCode.RESTART:
					if cur_code == EventCode.CHANGED or cur_code == EventCode.CHECKPOINT:
						if self._level_matches_state(prev_level, state):
							delta = delta + cur_ts - prev_ts
				prev_code = cur_code
				prev_ts = cur_ts
				prev_level = row['level']
			# Account for interval from last event to now: last event should be reliable indicator of level at time, regardless of type.
			if prev_level is not None and self._level_matches_state(prev_level, state):
				cur_ts = datetime.datetime.now()
				delta = delta + cur_ts - prev_ts

		return delta

	def get_recent_events(self, dev_id, count = 10, include_synthetic = False):
		# dev_id can be a single device id, or a list of device ids
		# we look only at CHANGED events unless include_synthetic is true, in which case we look at all events
		# XXX it would be nice to allow the cap to be specified as an age instead of a count (useful for showing
		# history of devices associated with an age query).
		# XXX the following 1,2,3 is hardcoded, and nothing probably wants the include_synthetic case anyway, and
		# in the other case it would be more efficient to use =1 instead of IN(1). But then we'd need another
		# permutation on the command string. Plus if we do the above age cap thing we need yet another permutation
		# on the command string. Need a better way to build SQL command strings.
		eligible_events = '1,2,3' if include_synthetic else str(EventCode.CHANGED)
		with self._lock:
			c = self._cursor
			if isinstance(dev_id, list):
				# XXX I have to do my own string formatting here to use IN (a,b,c) because sqlite3 won't let me pass a list,
				# or even a string full of commas, as a ? replacement. This isn't perfect, but clobbering to int, then to
				# string to join by comma, then concatenating into the SQL command string should be safe.
				ids_as_string = ','.join([str(int(did)) for did in dev_id])
				c.execute('SELECT sg_device_id, event_ts, event_code, level FROM device_events ' +
					'WHERE sg_device_id IN (' + ids_as_string + ') AND event_code IN (?) ORDER BY event_ts DESC LIMIT ?',
					(eligible_events, count))
			else:
				c.execute('SELECT sg_device_id, event_ts, event_code, level FROM device_events ' +
					'WHERE sg_device_id = ? AND event_code IN (?) ORDER BY event_ts DESC LIMIT ?',
					(dev_id, eligible_events, count))

			return [AttrDict({
				'device_id': row['sg_device_id'],
				'reason': EventCode.from_int(row['event_code']),
				'level': row['level'],
				'timestamp': row['event_ts']
			}) for row in c]

	# private helpers
	def _level_matches_state(self, level, state):
		return (level > 0) == (state != 0)

	def _checkpoint_all(self):
		logger.warn('database checkpoint requested')
		with self._lock:
			c = self._cursor
			c.execute('SELECT sg_device_id FROM device_map WHERE gateway_id <> ?', (AREA_MAGIC_GATEWAY_ID,))
			for row in c:
				dev_id = row[0]
				self._checkpoint_device_state(dev_id)
			self._commit()

	def _checkpoint_device_state(self, dev_id):
		# Internal helper function: requires lock, does not commit; caller must take care of locking and committing
		assert self._lock._is_owned() # XXX I want a way to check if owned *by me*!
		self._save_newest_knowledge(dev_id, EventCode.CHECKPOINT)

	def _save_newest_knowledge(self, dev_id, event_code, level = 0):
		# Used when saving a checkpoint or a change event: if the newest previous event for this device is a checkpoint,
		# overwrite it, otherwise add a new event.
		c = self._cursor
		current_ts = datetime.datetime.now().isoformat()
		# find newest record for dev_id
		c.execute('SELECT event_code, event_ts, level FROM device_events WHERE sg_device_id = ? ORDER BY event_ts DESC LIMIT 1', (dev_id, ))
		row = c.fetchone()
		# checkpoint events get replaced (with newer checkpoint, or explicit level change)
		if row is not None and row['event_code'] == EventCode.CHECKPOINT:
			old_ts = row['event_ts']
			if event_code == EventCode.CHECKPOINT: # reuse checkpoint by updating timestamp
				c.execute('UPDATE device_events SET event_ts = ? WHERE sg_device_id = ? AND event_ts = ?',
					(current_ts, dev_id, old_ts))
			else: # replace checkpoint with CHANGED event
				c.execute('UPDATE device_events SET event_code = ?, level = ?, event_ts = ? WHERE sg_device_id = ? AND event_ts = ?',
					(event_code, level, current_ts, dev_id, old_ts))
		else: # not a checkpoint event, so add a new event
			if event_code == EventCode.CHECKPOINT: # new checkpoint
				# We'd better take a checkpoint only after a previous record, so row.level should be safe to use here
				if row is None:
					logger.warn('No events for device %d, cannot checkpoint' % dev_id)
					return
				c.execute('INSERT INTO device_events(sg_device_id, event_code, level, event_ts) VALUES(?,?,?,?)',
					(dev_id, EventCode.CHECKPOINT, row['level'], current_ts))
			else: # new CHANGED event
				# NB that row may well be None here; we can't (and don't need to) reference it
				c.execute('INSERT INTO device_events(sg_device_id, event_code, level, event_ts) VALUES(?,?,?,?)',
					(dev_id, event_code, level, current_ts))

	def _commit(self):
		self._conn.commit()

	def _ts_from_string(self, ts_string):
		return dateutil.parser.parse(ts_string)

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
			
	def _create_schema(self):
		c = self._cursor
		sql_cmds = '''
		-- version the schema itself
		CREATE TABLE schema_version (object STRING PRIMARY KEY, version INTEGER NOT NULL);
		INSERT INTO schema_version VALUES('stargate', %d);

		-- map from IDs used by rest of Stargate (gateway name, and id relative only to that gateway) to unique integer 'sg_device_id' used by following tables
		CREATE TABLE device_map (gateway_id STRING NOT NULL, gateway_device_id STRING NOT NULL, sg_device_id INTEGER PRIMARY KEY AUTOINCREMENT);
		CREATE INDEX device_map_index ON device_map(gateway_id, gateway_device_id);

		-- device event history
		-- sg_device_id: index into device_map
		-- event_code: 1 == changed, 2 == status checkpoint (no change since previous event), 3 == restart (unknown since previous event)
		-- level: level associated with current event
		-- event_ts: timestamp
		CREATE TABLE device_events (sg_device_id INTEGER, event_code INTEGER, level INTEGER, event_ts STRING,
		                            FOREIGN KEY(sg_device_id) REFERENCES device_map(sg_device_id));
		''' % self._version # Yes, in general we should use db's ? string-formatting and not python's %, but this use is safe since we control the value of self.version
		c.executescript(sql_cmds)
		self._commit()

	def _upgrade_schema(self, from_version):
		if from_version > self._version:
			raise Exception('database version is from the future! (newer than runtime version)')
		raise Exception('db upgrade not implemented')

	def _install_signal_handlers(self):
		# XXX this should move somewhere more global, not part of persistence
		def handle_signal(signum, stack_frame):
			logger.warn("Received signal %d" % signum)
			self._checkpoint_all()
			if signum != signal.SIGHUP:
				logger.warn("Exiting on signal %d" % signum)
				sys.exit()

		signal.signal(signal.SIGHUP, handle_signal)
		signal.signal(signal.SIGINT, handle_signal)
		signal.signal(signal.SIGTERM, handle_signal)
		signal.signal(signal.SIGQUIT, handle_signal)

		# XXX I also want to catch exits due to werkzeug's reloader, which just calls sys.exit(3) directly.
		# So wrap sys.exit:
		real_sys_exit = sys.exit
		def persist_exit_wrapper(exitcode = 0):
			logger.warn("Checkpoint before exit")
			self._checkpoint_all()
			real_sys_exit(exitcode)
		sys.exit = persist_exit_wrapper

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
