"""IBM Past inventory and Future queue tests: no IBM credentials or network needed."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect,migrate
from gnosis_platform.identity import register,b64e,grant
from gnosis_platform.transactions import begin_consultation,finish_request
from gnosis_platform.ibm_inventory import (validate_archive,import_archive,approve_batch,hold_next,
                                            coin_reading,inventory_counts)
from gnosis_platform.ibm_future_queue import (queue_request,claim_next_submission,
                                              mark_submitted,list_needing_reconciliation)

SHA='a'*64

def archive():
    return {'schema':'gnosis.ibm_past.v1',
        'manifest':{'backend':'ibm_marrakesh','external_job_id':'job-abc-123',
          'circuit_sha256':SHA,'circuit_version':'v1','acquired_at':'2026-11-15T18:00:00Z',
          'submitted_at':'2026-11-15T17:59:00Z'},
        'samples':[{'sample_index':0,'coin_bits':'000111010101001101'},
                   {'sample_index':1,'coin_bits':'101100011011101010'}]}

class IBMFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'test.sqlite3');migrate(self.db)
        key=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw,
                                                                   serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(key))['account_id']
        grant(self.db,self.account,50,'test','ibm test',uuid4().hex)
        self.db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.account,))
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def past(self):
        return begin_consultation(self.db,account_id=self.account,
            service_id='iching.quantum_past',idempotency_key=uuid4().hex)
    def imported(self):
        doc=archive()
        digest=hashlib.sha256(json.dumps(doc).encode()).hexdigest()
        record=import_archive(self.db,doc,file_sha256=digest)
        return record,doc,digest
    def test_import_quarantine_and_deduplication(self):
        record,doc,digest=self.imported()
        self.assertTrue(record['created'])
        self.assertFalse(import_archive(self.db,doc,file_sha256=digest)['created'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM ibm_inventory_items').fetchone()[0],2)
        self.assertIsNone(hold_next(self.db,self.past()['consultation_id']))
        self.assertEqual(inventory_counts(self.db)[0]['batch_status'],'quarantined')
    def test_reject_invalid_source_records(self):
        doc=archive();doc['samples'][0]['coin_bits']='0'*17
        with self.assertRaises(ValueError):validate_archive(doc)
        doc=archive();doc['samples'][1]['sample_index']=0
        with self.assertRaises(ValueError):validate_archive(doc)
    def test_approval_and_unique_atomic_allocation(self):
        record,_,_=self.imported()
        with self.assertRaises(ValueError):
            approve_batch(self.db,record['batch_id'],operator='test',
                          verified_job_id='wrong',verified_circuit_sha256=SHA)
        approve_batch(self.db,record['batch_id'],operator='test',
                      verified_job_id='job-abc-123',verified_circuit_sha256=SHA)
        first=self.past()['consultation_id']
        second=self.past()['consultation_id']
        third=self.past()['consultation_id']
        a=hold_next(self.db,first)
        self.assertIsNotNone(a)
        self.assertEqual(a['item_id'],hold_next(self.db,first)['item_id'])
        b=hold_next(self.db,second)
        self.assertNotEqual(a['item_id'],b['item_id'])
        self.assertIsNone(hold_next(self.db,third))
        self.assertEqual(len(coin_reading(a['coin_bits'])['lines']),6)
    def test_future_claim_idempotent_and_noncharging(self):
        req=begin_consultation(self.db,account_id=self.account,
            service_id='iching.quantum_future',idempotency_key=uuid4().hex)
        self.assertEqual(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()[:],(40,10))
        q=queue_request(self.db,req['request_id'])
        self.assertEqual(queue_request(self.db,req['request_id'])['request_id'],q['request_id'])
        claimed=claim_next_submission(self.db)
        self.assertEqual(claimed['request_id'],q['request_id'])
        self.assertIsNone(claim_next_submission(self.db))
        self.assertEqual(list_needing_reconciliation(self.db)[0]['status'],'submitting')
        mark_submitted(self.db,q['request_id'],external_job_id='ibm-job-001',
                       backend='ibm_marrakesh',circuit_sha256=SHA,circuit_version='v1',shots=1)
        row=self.db.execute('SELECT status,external_job_id FROM ibm_future_jobs').fetchone()
        self.assertEqual(tuple(row),('submitted','ibm-job-001'))
        self.assertEqual(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()[:],(40,10))
        finish_request(self.db,q['request_id'],success=False)
        self.assertEqual(self.db.execute('SELECT available,reserved FROM credit_accounts').fetchone()[:],(50,0))

if __name__=='__main__':unittest.main()
