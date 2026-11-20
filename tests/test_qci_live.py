"""Milestone 3A: deterministic tests; no live QCI calls or token required."""
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
from gnosis_platform.qci_qrng import reading_from_bits, _parse_bits, QCIError
from gnosis_platform.consultations_api import router

class QCICastTests(unittest.TestCase):
    def test_coin_distribution_and_relating(self):
        bits=[0,0,0, 1,0,0, 1,1,0, 1,1,1, 0,1,0, 1,1,1]
        r=reading_from_bits(bits)
        self.assertEqual(r['lines'],[6,7,8,9,7,9])
        self.assertEqual(r['now_yang_bits_bottom_to_top'],[0,1,0,1,1,1])
        self.assertEqual(r['becoming_yang_bits_bottom_to_top'],[1,1,0,0,1,0])
        self.assertEqual(r['moving_positions_bottom_to_top'],[1,4,6])

    def test_invalid_response_rejected_without_fallback(self):
        for response in ([0]*17,[0]*19,[True]+[0]*17,['0']+[0]*17,[0.0]+[0]*17,{}):
            with self.assertRaises(QCIError):_parse_bits(response)

class QCIApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'qci.db'
        self.db=connect(self.path)
        migrate(self.db)
        key=Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(key))['account_id']
        grant(self.db,self.account,5,'test','qci',uuid4().hex)
        self.user={'account_id':self.account,'is_admin':1}
        self.app=FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[authenticated]=lambda:self.user
        self.patcher=patch('gnosis_platform.consultations_api.connect',lambda:connect(self.path))
        self.patcher.start()
        self.client=TestClient(self.app)
        self.env=patch.dict(os.environ,{'GNOSIS_ENABLE_QCI':'1','QCI_API_TOKEN':'fake-test-token','GNOSIS_ENABLE_CONSULTATION_SANDBOX':'0'})
        self.env.start()
    def tearDown(self):
        self.env.stop()
        self.client.close()
        self.patcher.stop()
        self.db.close()
        self.tmp.cleanup()

    def post(self,key=None):
        return self.client.post('/api/v1/consultations',json={
            'service_id':'iching.qrng_private','idempotency_key':key or uuid4().hex,
            'question':'A private inquiry','inquiry_style':'direct'})

    def test_success_stored_private_replay_and_zero_credit(self):
        call=[0]
        def fake_cast():
            call[0]+=1
            return reading_from_bits([0,1,0]*6),{'provider':'qci','n_samples':18,'test':True}
        with patch('gnosis_platform.qci_execution.cast',side_effect=fake_cast):
            key=uuid4().hex
            first=self.post(key)
            again=self.post(key)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(call[0],1)
        self.assertEqual(first.json()['result']['reading']['lines'],[7]*6)
        cid=first.json()['receipt']['consultation_id']
        self.assertEqual(self.client.get('/api/v1/consultations/'+cid).status_code,200)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(5,0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM provider_requests').fetchone()[0],1)
        self.user['account_id']='e'*64
        self.assertEqual(self.client.get('/api/v1/consultations/'+cid).status_code,404)

    def test_failed_provider_no_credit_or_fake_reading(self):
        with patch('gnosis_platform.qci_execution.cast',side_effect=QCIError('offline')):
            response=self.post()
        self.assertEqual(response.status_code,502,response.text)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(5,0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_results').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT status FROM consultations').fetchone()[0],'failed')

    def test_minimum_available_balance_and_catalog(self):
        catalog=self.client.get('/api/v1/services/catalog').json()['services']
        qci=next(x for x in catalog if x['service_id']=='iching.qrng_private')
        self.assertTrue(qci['available'])
        self.db.execute('UPDATE credit_accounts SET available=0 WHERE account_id=?',(self.account,))
        self.assertEqual(self.post().status_code,402)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM provider_requests').fetchone()[0],0)

if __name__=='__main__':unittest.main()
