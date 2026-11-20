import importlib.util
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location('gnosis_volume_monitor', Path(__file__).resolve().parents[1] / 'scripts' / 'gnosis_volume_monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

class VolumeMonitorTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE consultations(consultation_id INTEGER PRIMARY KEY, application_id TEXT, status TEXT, finished_at TEXT)')
        self.db.execute('CREATE TABLE reading_results(consultation_id INTEGER PRIMARY KEY)')
        self.now=datetime(2026,11,16,tzinfo=timezone.utc)
    def tearDown(self): self.db.close()
    def push(self, n, minutes_ago=30):
        stamp=(self.now-timedelta(minutes=minutes_ago)).isoformat(timespec='milliseconds').replace('+00:00','Z')
        for _ in range(n):
            cid=self.db.execute("INSERT INTO consultations(application_id,status,finished_at) VALUES('iching','completed',?)",(stamp,)).lastrowid
            self.db.execute('INSERT INTO reading_results VALUES (?)',(cid,))
    def test_strict_threshold(self):
        self.push(1000)
        self.assertEqual(monitor.evaluate(self.db,now=self.now)['volume_level'],'normal')
        self.push(1)
        self.assertEqual(monitor.evaluate(self.db,now=self.now)['volume_level'],'warning')
    def test_rolling_window(self):
        self.push(2501,minutes_ago=24*60+1)
        self.assertEqual(monitor.evaluate(self.db,now=self.now)['completed_readings_24h'],0)
        self.push(2501)
        self.assertEqual(monitor.evaluate(self.db,now=self.now)['volume_level'],'critical')
    def test_one_row_one_reading(self):
        self.push(1)
        self.assertEqual(monitor.evaluate(self.db,now=self.now)['completed_readings_24h'],1)
    def test_alert_transitions_dedup(self):
        c={'volume_level':'warning','completed_readings_24h':1300,'disk':None}
        state,events=monitor.alert_changes({},c)
        self.assertEqual(len(events),1)
        self.assertEqual(monitor.alert_changes({'levels':state},c)[1],[])
        c['volume_level']='normal'
        self.assertEqual(len(monitor.alert_changes({'levels':state},c)[1]),1)
if __name__=='__main__': unittest.main()
