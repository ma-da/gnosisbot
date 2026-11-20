"""M3C projection, history auth, backfill, and export tests; no QCI network calls."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect,migrate
from gnosis_platform.identity import b64e,register,grant
from gnosis_platform.transactions import begin_consultation,finish_request
from gnosis_platform.history_api import router
from gnosis_platform.auth_api import authenticated
from gnosis_platform.research import backfill
from gnosis_platform.research_export import export_jsonl

class ResearchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'test.sqlite3'
        self.db=connect(self.path);migrate(self.db)
        def account():
            raw=Ed25519PrivateKey.generate().public_key().public_bytes(
                serialization.Encoding.Raw,serialization.PublicFormat.Raw)
            return register(self.db,b64e(raw))['account_id']
        self.owner=account();self.other=account()
        grant(self.db,self.owner,5,'test','research',uuid4().hex)
        self.app=FastAPI();self.app.include_router(router)
        self.session={'account_id':self.owner,'is_admin':True}
        self.app.dependency_overrides[authenticated]=lambda:self.session
        self.patch=patch('gnosis_platform.history_api.connect',lambda:connect(self.path))
        self.patch.start()
        self.client=TestClient(self.app)

    def tearDown(self):
        self.client.close();self.patch.stop();self.db.close();self.temp.cleanup()

    def complete(self,raw=True):
        record=begin_consultation(self.db,account_id=self.owner,service_id='iching.qrng_private',
            idempotency_key=uuid4().hex,question='A research question')
        reading={'lines':[6,7,8,9,7,9],
          'coin_bits_bottom_to_top':['000','100','110','111','100','111'],
          'now_yang_bits_bottom_to_top':[0,1,0,1,1,1],
          'becoming_yang_bits_bottom_to_top':[1,1,0,0,1,0],
          'moving_positions_bottom_to_top':[1,4,6]}
        provenance={'provider':'qci','n_bits':16,'n_samples':2}
        if raw:provenance['raw_samples_decimal']=[30686,42816]
        finish_request(self.db,record['request_id'],success=True,
                       result_json=reading,provenance_json=provenance)
        return record['consultation_id']

    def test_atomic_projection_raw_and_access(self):
        cid=self.complete()
        fact=self.db.execute('SELECT * FROM reading_facts').fetchone()
        self.assertEqual((fact['moving_count'],fact['primary_mask'],fact['relating_mask']),(3,58,19))
        measurement=self.db.execute('SELECT * FROM reading_measurements').fetchone()
        self.assertEqual(measurement['measurement_status'],'raw_retained')
        self.assertEqual(json.loads(measurement['raw_payload_json']),[30686,42816])
        response=self.client.get('/api/v1/accounts/readings')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['total'],1)
        self.assertEqual(self.client.get('/api/v1/accounts/readings/'+cid).status_code,200)
        self.session['account_id']=self.other
        self.assertEqual(self.client.get('/api/v1/accounts/readings').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/accounts/readings/'+cid).status_code,404)

    def test_backfill_only_missing_records(self):
        cid=self.complete(raw=False)
        self.db.execute('DELETE FROM reading_facts WHERE consultation_id=?',(cid,))
        self.db.execute('DELETE FROM reading_measurements WHERE consultation_id=?',(cid,))
        self.assertEqual(backfill(self.db),1)
        self.assertEqual(backfill(self.db),0)
        self.assertEqual(self.db.execute('SELECT measurement_status FROM reading_measurements').fetchone()[0],
                         'derived_bits_only')

    def test_reject_invalid_coin_bits_before_settlement(self):
        record=begin_consultation(self.db,account_id=self.owner,service_id='iching.qrng_private',
            idempotency_key=uuid4().hex,question='Test')
        bad={'lines':[7]*6,'coin_bits_bottom_to_top':['000']*6}
        with self.assertRaises(ValueError):
            finish_request(self.db,record['request_id'],success=True,
                           result_json=bad,provenance_json={'provider':'qci'})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_results').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT status FROM consultations WHERE consultation_id=?',
                          (record['consultation_id'],)).fetchone()[0],'pending')

    def test_restricted_export_and_no_overwrite(self):
        self.complete()
        output=Path(self.temp.name)/'archive.jsonl'
        manifest=export_jsonl(self.db,output)
        self.assertEqual(manifest['record_count'],1)
        self.assertEqual(manifest['classification'],'RESTRICTED_NOT_PUBLIC')
        data=json.loads(output.read_text().splitlines()[0])
        self.assertEqual(data['question'],'A research question')
        self.assertEqual(data['raw_payload'],[30686,42816])
        with self.assertRaises(FileExistsError):export_jsonl(self.db,output)
if __name__=='__main__':unittest.main()
