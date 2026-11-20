import json
import os
import sqlite3
import unittest
from unittest.mock import patch
from gnosis_platform.ibm_trial_email import (prepared_message, send_completed_trial)

class FakeResponse:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return b'{"id":"resend-test-001"}'

class TrialEmailTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        CREATE TABLE service_requests (request_id TEXT PRIMARY KEY, consultation_id TEXT, service_id TEXT,credits_cost INTEGER,status TEXT);
        CREATE TABLE consultations (consultation_id TEXT PRIMARY KEY,account_id TEXT,status TEXT);
        CREATE TABLE ibm_future_jobs (request_id TEXT,status TEXT);
        CREATE TABLE reading_results (consultation_id TEXT);
        INSERT INTO service_requests VALUES ('req','consult','iching.quantum_future',10,'completed');
        INSERT INTO consultations VALUES ('consult','account','completed');
        INSERT INTO ibm_future_jobs VALUES ('req','completed');
        INSERT INTO reading_results VALUES ('consult');
        ''')
        self.env=patch.dict(os.environ,{
            'GNOSIS_ENABLE_TRIAL_EMAIL':'YES',
            'GNOSIS_TEST_NOTIFICATION_EMAIL':'trial@example.com',
            'GNOSIS_RESEND_FROM':'Gnosis <robot@gnosis.bot>',
            'RESEND_API_KEY':'re_not_a_real_key',
            'GNOSIS_PUBLIC_BASE_URL':'https://gnosis.bot',
        })
        self.env.start()
    def tearDown(self):self.env.stop();self.db.close()
    def test_no_email_without_full_settlement(self):
        self.db.execute("UPDATE ibm_future_jobs SET status='result_ready'")
        with self.assertRaises(ValueError):send_completed_trial(self.db,'req',transport=lambda *a,**k:FakeResponse())
    def test_sent_once_and_no_question_leak(self):
        captured=[]
        def transport(req,timeout=None):
            captured.append(json.loads(req.data));return FakeResponse()
        first=send_completed_trial(self.db,'req',transport=transport)
        self.assertEqual(first['status'],'sent')
        second=send_completed_trial(self.db,'req',transport=transport)
        self.assertEqual(second['status'],'sent')
        self.assertEqual(len(captured),1)
        self.assertEqual(captured[0]['to'],['trial@example.com'])
        self.assertNotIn('question',str(captured[0]).lower())
    def test_network_ambiguity_sticky(self):
        def offline(*a,**k):raise TimeoutError('unknown provider acceptance')
        with self.assertRaises(TimeoutError):send_completed_trial(self.db,'req',transport=offline)
        self.assertEqual(self.db.execute('SELECT status FROM ibm_trial_email_notifications').fetchone()[0],'needs_review')
        result=send_completed_trial(self.db,'req',transport=lambda *a,**k:FakeResponse())
        self.assertEqual(result['status'],'needs_review')
    def test_only_https_url(self):
        with self.assertRaises(ValueError):
            prepared_message(consultation_id='x',recipient='a@b.com',sender='x@y.com',base_url='http://example.com')

if __name__=='__main__':unittest.main()
