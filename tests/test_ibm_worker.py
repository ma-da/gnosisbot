"""Mock-only IBM worker lifecycle tests; never submit an IBM job."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from gnosis_platform.db import connect, migrate
from gnosis_platform.identity import b64e, register, grant
from gnosis_platform.transactions import begin_consultation
from gnosis_platform.ibm_future_queue import queue_request, claim_next_submission, mark_submitted
from gnosis_platform.ibm_worker import stage_result, settle_staged, submit_one, capacity_scenarios

class FakeBitArray:
    def __init__(self, strings): self.strings = strings
    def get_bitstrings(self): return self.strings
class FakeData:
    def __init__(self, coins, moves):
        self.coins = FakeBitArray(coins)
        self.moves = FakeBitArray(moves)
class FakePub:
    def __init__(self, coins, moves): self.data = FakeData(coins,moves)

class IBMWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'local.sqlite3');migrate(self.db)
        k=Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(k))['account_id']
        grant(self.db,self.account,50,'test','ibm-worker',uuid4().hex)
        self.db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.account,))
        req=begin_consultation(self.db,account_id=self.account,service_id='iching.quantum_future',
                               idempotency_key=uuid4().hex,question='Test IBM archive')
        self.req=req['request_id'];self.cid=req['consultation_id']
        queue_request(self.db,self.req)
        claim_next_submission(self.db)
        mark_submitted(self.db,self.req,external_job_id='realistic-test-id',backend='ibm_marrakesh',
                       circuit_sha256='a'*64,circuit_version='test-seed5',shots=128)
        self.spool=Path(self.tmp.name)/'spool'
        # Native register representation is MSB-first.
        coins=['010101010101010101']*100+['111111111111111111']*28
        moves=['000000']*100+['111111']*28
        self.fake=[FakePub(coins,moves)]
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def balance(self):
        return tuple(self.db.execute('SELECT available,reserved FROM credit_accounts WHERE account_id=?',(self.account,)).fetchone())
    def test_stage_then_settle_128_shots_and_one_research_fact(self):
        self.assertEqual(self.balance(),(40,10))
        staged=stage_result(self.db,self.req,result=self.fake,spool=self.spool,min_free_bytes=0)
        self.assertEqual(staged['shots'],128)
        self.assertEqual(self.balance(),(40,10))
        self.assertEqual(stage_result(self.db,self.req,result=self.fake,spool=self.spool,min_free_bytes=0)['shots'],128)
        done=settle_staged(self.db,self.req,spool=self.spool)
        self.assertEqual(done['status'],'completed')
        self.assertEqual(self.balance(),(40,0))
        self.assertTrue(settle_staged(self.db,self.req,spool=self.spool)['replayed'])
        reading=self.db.execute('SELECT * FROM reading_results WHERE consultation_id=?',(self.cid,)).fetchone()
        self.assertEqual(len(json.loads(reading['provenance_json'])['selection']['shots']),128)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_facts WHERE consultation_id=?',(self.cid,)).fetchone()[0],1)
        measurement=self.db.execute('SELECT * FROM reading_measurements WHERE consultation_id=?',(self.cid,)).fetchone()
        self.assertEqual(measurement['measurement_status'], 'raw_retained')
        self.assertEqual(measurement['sample_count'], 128)
        self.assertEqual(measurement['bits_per_sample'], 24)
        self.assertEqual(len(json.loads(measurement['raw_payload_json'])['shots']), 128)
    def test_corrupted_stage_cannot_charge(self):
        staged=stage_result(self.db,self.req,result=self.fake,spool=self.spool,min_free_bytes=0)
        p=Path(staged['spool_path'])
        obj=json.loads(p.read_text());obj['selection']['selected_shot_index']=127
        p.write_text(json.dumps(obj))
        with self.assertRaises(ValueError):settle_staged(self.db,self.req,spool=self.spool)
        self.assertEqual(self.balance(),(40,10))
    def test_live_submit_disabled_by_default(self):
        with self.assertRaises(RuntimeError):submit_one(self.db,backend_name='ibm_marrakesh')
        self.assertEqual(self.db.execute('SELECT status FROM ibm_future_jobs').fetchone()[0],'submitted')
    def test_disk_sizing(self):
        self.assertEqual(capacity_scenarios()['1000']['annual_gb'],18.25)

if __name__=='__main__':unittest.main()
