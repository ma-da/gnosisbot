"""Offline M4D integration tests; no IBM or Resend network traffic."""
import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet

from gnosis_platform.db import connect,migrate
from gnosis_platform.transactions import begin_consultation
from gnosis_platform.ibm_future_queue import queue_request
from quantum.iching.medoid import select_medoid,canonical_payload
from gnosis_platform.ibm_worker import settle_staged
from gnosis_platform.account_email import begin_email_verification,complete_email_verification
from gnosis_platform.completion_outbox import dispatch_one,reconcile_completed
from gnosis_platform.account_hub_api import account_hub
from gnosis_platform.event_worker import cycle

class FakeResponse:
    def __init__(self):self.body=json.dumps({'id':'email-test-123'}).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return self.body

class AccountLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbfile=Path(self.tmp.name)/'gnosis.db'
        self.spool=Path(self.tmp.name)/'spool'
        self.spool.mkdir()
        self.env=patch.dict(os.environ,{
            'GNOSIS_DB_PATH':str(self.dbfile),
            'GNOSIS_CONTACT_ENCRYPTION_KEY':Fernet.generate_key().decode(),
            'GNOSIS_ENABLE_COMPLETION_EMAIL':'YES',
            'RESEND_API_KEY':'re_unit_test',
            'GNOSIS_ENABLE_TRIAL_EMAIL': 'NO',
            'GNOSIS_TEST_NOTIFICATION_EMAIL': '',
            'GNOSIS_RESEND_FROM':'Gnosis <readings@gnosis.bot>',
            'GNOSIS_PUBLIC_BASE_URL':'https://gnosis.bot',
        })
        self.env.start();self.addCleanup(self.env.stop)
        self.db=connect(self.dbfile);self.addCleanup(self.db.close)
        migrate(self.db)
        self.account_id='a'*64
        self.db.execute('INSERT INTO accounts(account_id,is_admin) VALUES(?,1)',(self.account_id,))
        self.db.execute('INSERT INTO credit_accounts(account_id,available,reserved) VALUES(?,50,0)',(self.account_id,))

    def create_settled(self):
        request=begin_consultation(self.db,account_id=self.account_id,
            service_id='iching.quantum_future',idempotency_key=('test-' + '0' * 16),
            question='Private example question')
        queue_request(self.db,request['request_id'])
        self.db.execute('''UPDATE ibm_future_jobs SET status='result_ready',backend='ibm_marrakesh',
          external_job_id='job-tested',circuit_sha256=?,circuit_version='v1',shots=128,
          submitted_at='2026-11-16T00:00:00Z' WHERE request_id=?''',
          ('f'*64,request['request_id']))
        # The raw batch contains 128 distinct indexed records, all retained.
        shots=[{'coin_bits':format(i,'018b'),'moving_qpu_bits':'000000'} for i in range(128)]
        selection=canonical_payload(select_medoid(shots))
        document={'schema':'gnosis.ibm_result.v1','request_id':request['request_id'],
            'external_job_id':'job-tested','backend':'ibm_marrakesh',
            'circuit_sha256':'f'*64,'circuit_version':'v1',
            'submitted_at':'2026-11-16T00:00:00Z',
            'staged_at':'2026-11-16T00:00:00Z','selection':selection}
        (self.spool/(request['request_id']+'.json')).write_text(json.dumps(document))
        return request

    def test_atomic_settlement_outbox_and_one_research_observation(self):
        r=self.create_settled()
        result=settle_staged(self.db,r['request_id'],spool=self.spool)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()[:],(40,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM reading_facts').fetchone()[0],1)
        row=self.db.execute('SELECT status,consultation_id FROM gnosis_completion_outbox').fetchone()
        self.assertEqual(row['status'],'awaiting_contact')
        saved=json.loads(self.db.execute('SELECT provenance_json FROM reading_results').fetchone()[0])
        self.assertEqual(len(saved['selection']['shots']),128)
        self.assertEqual(settle_staged(self.db,r['request_id'],spool=self.spool)['replayed'],True)
        self.assertEqual(self.db.execute('SELECT count(*) FROM gnosis_completion_outbox').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()[:],(40,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM credit_ledger WHERE kind="settle"').fetchone()[0],1)

    def test_verified_email_dispatch_and_deduplication(self):
        r=self.create_settled()
        settle_staged(self.db,r['request_id'],spool=self.spool)
        token,email=begin_email_verification(self.db,account_id=self.account_id,email='example@example.org')
        self.assertEqual(email,'example@example.org')
        complete_email_verification(self.db,account_id=self.account_id,token=token)
        seen=[]
        def mock_transport(req,timeout):
            self.assertEqual(timeout,20)
            message=json.loads(req.data)
            seen.append(message)
            self.assertEqual(message['to'],['example@example.org'])
            self.assertNotIn('Private example question',str(message))
            self.assertIn('/account.html',message['text'])
            return FakeResponse()
        result=dispatch_one(self.db,transport=mock_transport)
        self.assertEqual(result['status'],'sent')
        self.assertEqual(dispatch_one(self.db,transport=mock_transport)['status'],'none_due')
        self.assertEqual(len(seen),1)

    def test_unverified_contact_cannot_receive_completion(self):
        r=self.create_settled();settle_staged(self.db,r['request_id'],spool=self.spool)
        self.assertEqual(dispatch_one(self.db)['status'],'none_due')
        self.assertEqual(self.db.execute('SELECT status FROM gnosis_completion_outbox').fetchone()[0],'awaiting_contact')

    def test_hub_only_shows_own_consultations_not_raw_shots(self):
        r=self.create_settled();settle_staged(self.db,r['request_id'],spool=self.spool)
        user={'account_id':self.account_id,'available':40,'reserved':0,'account_group':'standard','is_admin':1}
        data=account_hub(user=user)
        self.assertEqual(data['account']['credits'],40)
        self.assertEqual(data['activity']['total'],1)
        item=data['activity']['items'][0]
        self.assertEqual(item['service_id'],'iching.quantum_future')
        self.assertEqual(item['email_status'],'awaiting_contact')
        self.assertNotIn('selection',json.dumps(item))
        self.assertIn('?reading=',item['open_url'])

    def test_worker_never_submits_without_paid_opt_in(self):
        # Reaching the worker with a queued job, auto-submit OFF, doesn't contact IBM.
        r=begin_consultation(self.db,account_id=self.account_id,service_id='iching.quantum_future',
             idempotency_key='m4d-worker-check-12345')
        queue_request(self.db,r['request_id'])
        with patch('gnosis_platform.event_worker.submit_one') as called:
            output=cycle(self.db,spool=self.spool)
            called.assert_not_called()
        self.assertIsNone(output['submitted'])
        self.assertEqual(self.db.execute('SELECT status FROM ibm_future_jobs').fetchone()[0],'queued')

    def test_failed_provider_delivery_needs_review_without_repeat(self):
        r=self.create_settled();settle_staged(self.db,r['request_id'],spool=self.spool)
        token,_=begin_email_verification(self.db,account_id=self.account_id,email='owner@example.org')
        complete_email_verification(self.db,account_id=self.account_id,token=token)
        def failing(req,timeout):raise OSError('uncertain network outcome')
        self.assertEqual(dispatch_one(self.db,transport=failing)['status'],'needs_review')
        self.assertEqual(dispatch_one(self.db,transport=failing)['status'],'none_due')
        self.assertEqual(self.db.execute('SELECT attempts FROM gnosis_completion_outbox').fetchone()[0],1)

if __name__=='__main__':unittest.main()
