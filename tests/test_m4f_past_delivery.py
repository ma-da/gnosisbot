"""M4F tests: stock gate, unique delivery, refund, replay, research and provenance."""
import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect,migrate
from gnosis_platform.identity import register,b64e,grant
from gnosis_platform.transactions import begin_consultation
from gnosis_platform.ibm_inventory import import_archive,approve_batch
from gnosis_platform.ibm_past_delivery import deliver_pending,available_count,recover_pending

SHA='a'*64

def archive():
    return {'schema':'gnosis.ibm_past.v1','manifest':{
      'backend':'ibm_marrakesh','external_job_id':'qpu-job-abc123',
      'circuit_sha256':SHA,'circuit_version':'iching-v1',
      'acquired_at':'2026-11-15T18:00:00Z','submitted_at':'2026-11-15T17:59:00Z'},
      'samples':[{'sample_index':0,'coin_bits':'000111010101001101'},
                 {'sample_index':1,'coin_bits':'101100011011101010'}]}

class M4FPastTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'test.sqlite3')
        migrate(self.db)
        raw=Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(raw))['account_id']
        grant(self.db,self.account,20,'test','m4f',uuid4().hex)
        self.db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.account,))
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def stock(self,approve=True):
        doc=archive()
        imported=import_archive(self.db,doc,file_sha256=hashlib.sha256(json.dumps(doc).encode()).hexdigest())
        if approve: approve_batch(self.db,imported['batch_id'],operator='test',verified_job_id='qpu-job-abc123',verified_circuit_sha256=SHA)
        return imported
    def submit(self, idem=None):
        return begin_consultation(self.db,account_id=self.account,service_id='iching.quantum_past',
            idempotency_key=idem or uuid4().hex, question='Past sample test')
    def balance(self):
        return tuple(self.db.execute('SELECT available,reserved FROM credit_accounts WHERE account_id=?',(self.account,)).fetchone())
    def test_quarantined_stock_unavailable_and_refund(self):
        self.stock(approve=False)
        self.assertEqual(available_count(self.db),0)
        req=self.submit();self.assertEqual(self.balance(),(15,5))
        result=deliver_pending(self.db,req['request_id'])
        self.assertEqual(result['status'],'out_of_stock')
        self.assertEqual(self.balance(),(20,0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_results').fetchone()[0],0)
    def test_atomic_result_one_research_fact_and_consumption(self):
        self.stock()
        req=self.submit();self.assertEqual(self.balance(),(15,5))
        result=deliver_pending(self.db,req['request_id'])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.balance(),(15,0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_results').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_facts').fetchone()[0],1)
        row=self.db.execute('SELECT state,consultation_id FROM ibm_inventory_items WHERE item_id=?',(result['item_id'],)).fetchone()
        self.assertEqual(row['state'],'consumed');self.assertEqual(row['consultation_id'],req['consultation_id'])
        stored=self.db.execute('SELECT provenance_json,reading_json FROM reading_results').fetchone()
        self.assertEqual(json.loads(stored['provenance_json'])['provider'],'ibm_inventory')
        self.assertEqual(len(json.loads(stored['reading_json'])['lines']),6)
        again=deliver_pending(self.db,req['request_id'])
        self.assertTrue(again['replayed']);self.assertEqual(self.balance(),(15,0))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM ibm_inventory_items WHERE state='consumed'").fetchone()[0],1)
    def test_two_customers_cannot_receive_same_sample(self):
        self.stock()
        a=deliver_pending(self.db,self.submit()['request_id'])
        b=deliver_pending(self.db,self.submit()['request_id'])
        self.assertNotEqual(a['item_id'],b['item_id'])
        c=deliver_pending(self.db,self.submit()['request_id'])
        self.assertEqual(c['status'],'out_of_stock')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_facts').fetchone()[0],2)
        self.assertEqual(self.balance(),(10,0))
    def test_transaction_failure_rolls_back_inventory_and_credits(self):
        self.stock()
        req=self.submit()
        with patch('gnosis_platform.ibm_past_delivery.project_completed',
                   side_effect=RuntimeError('research projection disk failure')):
            with self.assertRaisesRegex(RuntimeError,'research projection disk failure'):
                deliver_pending(self.db,req['request_id'])
        self.assertEqual(self.balance(),(15,5))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reading_results').fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM ibm_inventory_items WHERE state='consumed'").fetchone()[0],0)
        self.assertEqual(deliver_pending(self.db,req['request_id'])['status'],'completed')
        self.assertEqual(self.balance(),(15,0))

    def test_restart_recovery_of_pending_admission(self):
        self.stock();req=self.submit()
        self.assertEqual(recover_pending(self.db),[{'status':'completed','replayed':False,
            'consultation_id':req['consultation_id'],'item_id':self.db.execute('SELECT item_id FROM ibm_inventory_items WHERE consultation_id=?',(req['consultation_id'],)).fetchone()['item_id'],
            'backend':'ibm_marrakesh'}])
        self.assertEqual(recover_pending(self.db),[])

if __name__=='__main__':unittest.main()
