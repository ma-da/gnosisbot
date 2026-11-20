"""M4F API: stock gates, approval, historic result delivery without IBM jobs."""
import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect,migrate
from gnosis_platform.identity import b64e,register,grant
from gnosis_platform.auth_api import authenticated
from gnosis_platform.ibm_inventory import import_archive,approve_batch
from gnosis_platform.consultations_api import router

class PastAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
        self.db=connect(self.path);migrate(self.db)
        raw=Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(raw))['account_id']
        grant(self.db,self.account,15,'test','m4f',uuid4().hex)
        self.db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.account,))
        user={'account_id':self.account,'is_admin':True}
        self.app=FastAPI();self.app.include_router(router)
        self.app.dependency_overrides[authenticated]=lambda:user
        self.connpatch=patch('gnosis_platform.consultations_api.connect', lambda:connect(self.path))
        self.connpatch.start();self.client=TestClient(self.app)
        self.env=patch.dict(os.environ,{'GNOSIS_ENABLE_IBM_PAST':'1','GNOSIS_ENABLE_QCI':'0',
                          'QCI_API_TOKEN':'','GNOSIS_ENABLE_NIST':'0'})
        self.env.start()
    def tearDown(self):
        self.env.stop();self.client.close();self.connpatch.stop();self.db.close();self.tmp.cleanup()
    def stock(self,approved=True):
        data={'schema':'gnosis.ibm_past.v1',
         'manifest':{'backend':'ibm_marrakesh','external_job_id':'dbt-qpu-pilot-001',
          'circuit_sha256':'e'*64,'circuit_version':'iching_now_becoming_24q_seed5_v1',
          'acquired_at':'2026-11-16T04:00:00Z','submitted_at':'2026-11-16T03:59:00Z'},
         'samples':[{'sample_index':0,'coin_bits':'000111010101001101','moving_qpu_bits':'110000'}]}
        r=import_archive(self.db,data,file_sha256=hashlib.sha256(json.dumps(data).encode()).hexdigest())
        if approved:
            approve_batch(self.db,r['batch_id'],operator='operator',
                verified_job_id=data['manifest']['external_job_id'],
                verified_circuit_sha256=data['manifest']['circuit_sha256'])
    def available(self):
        svc=self.client.get('/api/v1/services/catalog').json()['services']
        return next(s for s in svc if s['service_id']=='iching.quantum_past')
    def post(self,idem=None):
        return self.client.post('/api/v1/consultations', json={'service_id':'iching.quantum_past',
                    'idempotency_key':idem or uuid4().hex,'question':'Archived reading'})
    def test_catalog_requires_enabled_approved_stock(self):
        self.assertFalse(self.available()['available'])
        self.stock(False);self.assertFalse(self.available()['available'])
        with patch.dict(os.environ,{'GNOSIS_ENABLE_IBM_PAST':'0'}):
            self.assertFalse(self.available()['available'])
        batch=self.db.execute('SELECT batch_id FROM ibm_inventory_batches').fetchone()['batch_id']
        approve_batch(self.db,batch,operator='test',verified_job_id='dbt-qpu-pilot-001',verified_circuit_sha256='e'*64)
        self.assertTrue(self.available()['available'])
    def test_synchronous_delivery_replay_history_and_last_stock(self):
        self.stock(True);key=uuid4().hex
        first=self.post(key);self.assertEqual(first.status_code,200,first.text)
        data=first.json();self.assertEqual(data['state'],'completed')
        self.assertEqual(data['result']['provenance']['provider'],'ibm_inventory')
        self.assertEqual(data['result']['reading']['moving_qpu_bits_bottom_to_top'],'110000')
        self.assertEqual(self.db.execute('SELECT count(*) FROM reading_facts').fetchone()[0],1)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(10,0))
        self.assertEqual(self.post(key).status_code,200)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(10,0))
        self.assertFalse(self.available()['available'])
        second=self.post();self.assertEqual(second.status_code,503,second.text)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(10,0))
    def test_no_inventory_or_disabled_service_never_charges(self):
        self.assertEqual(self.post().status_code,503)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(15,0))
        with patch.dict(os.environ,{'GNOSIS_ENABLE_IBM_PAST':'0'}):
            self.assertEqual(self.post().status_code,503)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(15,0))

if __name__=='__main__':unittest.main()
