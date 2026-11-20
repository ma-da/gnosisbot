"""Milestone 2B API tests, isolated SQLite, no provider calls."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect, migrate
from gnosis_platform.identity import b64e, register, grant
from gnosis_platform.auth_api import authenticated
from gnosis_platform.consultations_api import router

class ConsultationApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'m2b.db'
        self.db=connect(self.path)
        migrate(self.db)
        key=Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(key))['account_id']
        grant(self.db,self.account,20,'test-admin','testing',uuid4().hex)
        self.user={'account_id':self.account,'is_admin':1}
        self.app=FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[authenticated]=lambda:self.user
        self.patched=patch('gnosis_platform.consultations_api.connect',lambda:connect(self.path))
        self.patched.start()
        self.client=TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.patched.stop()
        self.db.close()
        self.tmp.cleanup()

    def begin(self, token=None):
        return self.client.post('/api/v1/consultations',json={
            'service_id':'iching.quantum_future', 'idempotency_key':token or uuid4().hex,
            'question':'Does the test charge me?'})

    def test_catalog_honestly_disables_all_server_services(self):
        response=self.client.get('/api/v1/services/catalog')
        self.assertEqual(response.status_code,200)
        services={s['service_id']:s for s in response.json()['services']}
        self.assertTrue(services['iching.classic']['available'])
        self.assertFalse(services['iching.qrng_private']['available'])
        self.assertFalse(services['iching.quantum_future']['available'])
        self.assertFalse(services['iching.qrng_private']['fallback_active'])

    def test_unauthenticated_rejected(self):
        self.app.dependency_overrides.clear()
        response=self.client.get('/api/v1/consultations')
        self.assertEqual(response.status_code,401)

    def test_non_sandbox_cannot_reserve_credits(self):
        with patch.dict(os.environ,{'GNOSIS_ENABLE_CONSULTATION_SANDBOX':'0'}):
            response=self.begin()
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.db.execute('SELECT count(*) FROM service_requests').fetchone()[0],0)

    def test_non_admin_cannot_enable_sandbox(self):
        self.user['is_admin']=0
        with patch.dict(os.environ,{'GNOSIS_ENABLE_CONSULTATION_SANDBOX':'1'}):
            response=self.begin()
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.db.execute('SELECT count(*) FROM service_requests').fetchone()[0],0)

    def test_sandbox_immediate_refund_replay_and_history(self):
        token=uuid4().hex
        with patch.dict(os.environ,{'GNOSIS_ENABLE_CONSULTATION_SANDBOX':'1'}):
            first=self.begin(token)
            again=self.begin(token)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(again.status_code,200,again.text)
        receipt=first.json()['receipt']
        self.assertEqual(receipt['status'],'failed')
        self.assertEqual(receipt['consultation_id'],again.json()['receipt']['consultation_id'])
        self.assertFalse(first.json()['provider_called'])
        self.assertEqual(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()[:],(20,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM service_requests').fetchone()[0],1)
        history=self.client.get('/api/v1/consultations')
        self.assertEqual(history.status_code,200)
        self.assertEqual(history.json()['total'],1)
        detail=self.client.get('/api/v1/consultations/'+receipt['consultation_id'])
        self.assertEqual(detail.status_code,200)
        self.assertEqual(detail.json()['request_status'],'failed')
        self.assertNotIn('result',detail.json())

    def test_other_account_history_not_visible(self):
        with patch.dict(os.environ,{'GNOSIS_ENABLE_CONSULTATION_SANDBOX':'1'}):
            first=self.begin()
        cid=first.json()['receipt']['consultation_id']
        self.user['account_id']='e'*64
        self.assertEqual(self.client.get('/api/v1/consultations/'+cid).status_code,404)
        self.assertEqual(self.client.get('/api/v1/consultations').json()['total'],0)

    def test_sandbox_idempotency_conflict(self):
        token=uuid4().hex
        with patch.dict(os.environ,{'GNOSIS_ENABLE_CONSULTATION_SANDBOX':'1'}):
            first=self.begin(token)
            second=self.client.post('/api/v1/consultations',json={
                'service_id':'iching.quantum_future','idempotency_key':token,'question':'Different question'})
        self.assertEqual(first.status_code,200)
        self.assertEqual(second.status_code,409)

if __name__=='__main__': unittest.main()
