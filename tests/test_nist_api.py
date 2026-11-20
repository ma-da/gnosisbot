"""Provider integration tests: idempotence, refunds, account ownership, catalog."""
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
from gnosis_platform.db import connect,migrate
from gnosis_platform.identity import b64e,register,grant
from gnosis_platform.auth_api import authenticated
from gnosis_platform.qci_qrng import reading_from_bits
from gnosis_platform.nist_beacon import NISTError
from gnosis_platform.consultations_api import router

class NISTApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'nist.db'
        self.db=connect(self.path)
        migrate(self.db)
        pub=Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(pub))['account_id']
        grant(self.db,self.account,5,'test','nist',uuid4().hex)
        self.user={'account_id':self.account,'is_admin':1}
        self.app=FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[authenticated]=lambda:self.user
        self.patcher=patch('gnosis_platform.consultations_api.connect',lambda:connect(self.path))
        self.patcher.start()
        self.client=TestClient(self.app)
        self.env=patch.dict(os.environ,{'GNOSIS_ENABLE_NIST':'1','GNOSIS_ENABLE_CONSULTATION_SANDBOX':'0'})
        self.env.start()
    def tearDown(self):
        self.env.stop();self.client.close();self.patcher.stop();self.db.close();self.tmp.cleanup()
    def post(self,key=None):
        return self.client.post('/api/v1/consultations',json={
            'service_id':'iching.qrng_public','idempotency_key':key or uuid4().hex,
            'question':'Public inquiry','inquiry_style':'direct'})
    def test_reproducible_one_cast_once_and_no_debit(self):
        seen=[]
        def fake_cast(rid):
            seen.append(rid)
            return reading_from_bits([0,1,0]*6),{'provider':'nist','n_samples':18,
                 'n_bits':1,'test':True,'derivation_request_id':rid}
        with patch('gnosis_platform.nist_execution.cast',side_effect=fake_cast):
            idem=uuid4().hex
            first=self.post(idem)
            second=self.post(idem)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(len(seen),1)
        self.assertEqual(first.json()['result']['reading']['lines'],[7]*6)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(5,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM reading_results').fetchone()[0],1)
        cid=first.json()['receipt']['consultation_id']
        self.assertEqual(self.client.get('/api/v1/consultations/'+cid).status_code,200)
    def test_provider_failure_no_fake_result_or_charge(self):
        with patch('gnosis_platform.nist_execution.cast',side_effect=NISTError('stale')):
            r=self.post()
        self.assertEqual(r.status_code,502,r.text)
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()),(5,0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_results').fetchone()[0],0)
    def test_catalog_toggle(self):
        entries=self.client.get('/api/v1/services/catalog').json()['services']
        nist=next(x for x in entries if x['service_id']=='iching.qrng_public')
        self.assertTrue(nist['available'])
        with patch.dict(os.environ,{'GNOSIS_ENABLE_NIST':'0'}):
            entries=self.client.get('/api/v1/services/catalog').json()['services']
        self.assertFalse(next(x for x in entries if x['service_id']=='iching.qrng_public')['available'])
    def test_no_credit_even_with_five_credit_balance(self):
        self.db.execute('UPDATE credit_accounts SET available=0 WHERE account_id=?',(self.account,))
        self.db.commit()
        self.assertEqual(self.post().status_code,402)

if __name__=='__main__':unittest.main()
