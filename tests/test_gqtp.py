import json, sqlite3, tempfile, unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from gnosis_platform import gqtp as g
from gnosis_platform.db import connect,migrate
from gnosis_platform.identity import register,b64e,grant
from gnosis_platform.transactions import begin_consultation,finish_request
from gnosis_platform.ibm_inventory import import_archive,approve_batch
from gnosis_platform.ibm_past_delivery import deliver_pending,available_count
from gnosis_platform.rune_past_inventory import import_batch,approve,PROFILES
from gnosis_platform.rune_production import run_claimed

class GQTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'db.sqlite');migrate(self.db)
        self.key=Ed25519PrivateKey.generate();self.pk=g.public_key(self.key)
        self.account=register(self.db,b64e(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)))['account_id']
        grant(self.db,self.account,100,'test','test',uuid4().hex);self.db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.account,))
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def count(self,table):return self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    def begin(self,s='iching.qrng_private'):return begin_consultation(self.db,account_id=self.account,service_id=s,idempotency_key=uuid4().hex,question='private question not public')
    def finish(self,r):return finish_request(self.db,r['request_id'],success=True,result_json={'lines':[7]*6},provenance_json={'provider':'qci','private':'secret raw'})
    def stock(self):
        meta=dict(backend='ibm_marrakesh',external_job_id='test-ibm-job',circuit_sha256='a'*64,circuit_version='test-v1',acquired_at='2026-11-18T04:07:37Z',submitted_at='2026-11-18T04:07:31Z')
        doc={'schema':'gnosis.ibm_past.v1','manifest':meta,'samples':[{'sample_index':i,'coin_bits':'0'*18,'moving_qpu_bits':'1'*6} for i in range(14)]}
        bid=import_archive(self.db,doc,file_sha256='b'*64)['batch_id'];g.note_qualification(self.db,bid,meta|{'mode':'iching','archive_sha256':'b'*64,'remote_measurements_match':True,'qpu_seconds':2});return bid
    def release(self,bid):
        n=g.checkpoint(self.db,self.key)['checkpoint']['tree_size'];g.release_batch(self.db,'test-ibm-job',n,proof_sha256='c'*64,operator='mock test verification')
        approve_batch(self.db,bid,operator='tester',verified_job_id='test-ibm-job',verified_circuit_sha256='a'*64)
    def test_merkle_all_odd_even_sizes_and_corruption(self):
        for n in range(1,34):
            ev=[{'seq':i} for i in range(n)];leaves=[g.leaf(g.canonical(e)) for e in ev];r=g.root(leaves).hex()
            for i,e in enumerate(ev):
                path=g.proof(leaves,i);self.assertTrue(g.verify_proof(e,i,n,path,r));self.assertFalse(g.verify_proof({'seq':-1},i,n,path,r));self.assertFalse(g.verify_proof(e,i,n,path+['0'*64],r))
    def test_rfc_domain_separation(self):
        self.assertEqual(g.root([]),g.sha(b''));self.assertEqual(g.root([g.leaf(b'a')]),g.sha(b'\x00a'));self.assertEqual(g.root([g.leaf(b'a'),g.leaf(b'b')]),g.sha(b'\x01'+g.sha(b'\x00a')+g.sha(b'\x00b')))
    def test_atomic_new_completion_receipt_tampering_and_replay(self):
        r=self.begin();self.finish(r);self.finish(r);self.assertEqual(self.count('gqtp_events'),1)
        receipt=g.receipt(self.db,r['consultation_id']);self.assertIsNone(receipt['checkpoint']);first=g.checkpoint(self.db,self.key);self.assertEqual(first,g.checkpoint(self.db,self.key));receipt=g.receipt(self.db,r['consultation_id']);self.assertTrue(g.verify_receipt(receipt,self.pk));self.assertFalse(g.verify_receipt(receipt,g.public_key(Ed25519PrivateKey.generate())))
        self.assertNotIn('private question',str(g.events(self.db)));self.assertNotIn('secret raw',str(g.events(self.db)));self.assertNotIn(r['consultation_id'],str(g.events(self.db)))
        receipt['saved_bytes']['reading_json']='{}';self.assertFalse(g.verify_receipt(receipt,self.pk))
        self.finish(self.begin());second=g.checkpoint(self.db,self.key);self.assertEqual(second['checkpoint']['previous_checkpoint_sha256'],g.digest_value(first))
        self.assertEqual(g.root([g.leaf(g.canonical(e)) for e in g.events(self.db,1)]).hex(),first['checkpoint']['root'])
    def test_rollback_on_ledger_failure(self):
        r=self.begin()
        with patch.object(g,'record_completion',side_effect=RuntimeError('ledger failure')):
            with self.assertRaises(RuntimeError):self.finish(r)
        self.assertEqual(self.count('reading_results'),0);self.assertEqual(self.count('gqtp_events'),0);self.assertEqual(self.db.execute('SELECT status FROM service_requests').fetchone()[0],'pending');self.finish(r);self.assertEqual(self.count('gqtp_events'),1)
    def test_legacy_backfill_is_explicit_and_idempotent(self):
        r=self.begin()
        with patch.object(g,'record_completion'):self.finish(r)
        self.assertEqual(g.backfill(self.db),1);self.assertEqual(g.backfill(self.db),0);self.assertEqual(g.events(self.db)[0]['historical_backfill'],1)
    def test_demo_reserve_and_distinct_equal_physical_samples(self):
        g.enable_inventory_guard(self.db);bid=self.stock()
        with self.assertRaises(sqlite3.IntegrityError):approve_batch(self.db,bid,operator='test',verified_job_id='test-ibm-job',verified_circuit_sha256='a'*64)
        result=g.register_batch(self.db,'iching',bid,demo_count=12,confirm_unrevealed=True);self.assertEqual(result['commercial_count'],2);self.assertEqual(self.count('gqtp_items'),14);self.assertEqual(available_count(self.db),0)
        with self.assertRaises(ValueError):g.register_batch(self.db,'iching',bid,confirm_unrevealed=True)
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE ibm_inventory_items SET coin_bits=? WHERE sample_index=12",('1'*18,))
        self.release(bid);self.assertEqual(available_count(self.db),2)
        a,b=self.begin('iching.quantum_past'),self.begin('iching.quantum_past');x=deliver_pending(self.db,a['request_id']);y=deliver_pending(self.db,b['request_id']);self.assertNotEqual(x['item_id'],y['item_id']);self.assertEqual(self.count('gqtp_deliveries'),2);self.assertEqual(available_count(self.db),0)
        deliver_pending(self.db,a['request_id']);self.assertEqual(self.count('gqtp_deliveries'),2)
        g.checkpoint(self.db,self.key);r=g.receipt(self.db,a['consultation_id']);self.assertTrue(g.verify_receipt(r,self.pk));r['inventory_receipt']['opening']['raw']['coin_bits']='1'*18;self.assertFalse(g.verify_receipt(r,self.pk))
    def test_immutable_events_and_wrong_signing_key(self):
        self.finish(self.begin());g.checkpoint(self.db,self.key)
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM gqtp_events')
        with self.assertRaises(ValueError):g.checkpoint(self.db,Ed25519PrivateKey.generate())
    def test_rune_pouch_reserved_inventory_commit_and_replay(self):
        g.enable_inventory_guard(self.db);sha,version=PROFILES['pouch'];meta=dict(mode='pouch',backend='ibm_marrakesh',external_job_id='pouch-test-123',circuit_sha256=sha,circuit_version=version,archive_sha256='d'*64,acquired_at='2026-11-18T04:07:37Z',submitted_at='2026-11-18T04:07:31Z',remote_measurements_match=True,qpu_seconds=2)
        bid=import_batch(self.db,meta,[[0,0,0]]*127+[[31,0,0]])['batch_id'];g.note_qualification(self.db,bid,meta)
        m=g.register_batch(self.db,'pouch',bid,confirm_unrevealed=True);self.assertEqual(m['commercial_count'],127);self.assertEqual(m['excluded_count'],1)
        n=g.checkpoint(self.db,self.key)['checkpoint']['tree_size'];g.release_batch(self.db,meta['external_job_id'],n,proof_sha256='e'*64,operator='mock test verification');approve(self.db,bid,operator='test',job_id=meta['external_job_id'],profile_sha=sha,confirm_unrevealed=True)
        r=self.begin('runes.pouch.quantum_past');self.assertEqual(run_claimed(self.db,r),'completed');g.checkpoint(self.db,self.key);self.assertTrue(g.verify_receipt(g.receipt(self.db,r['consultation_id']),self.pk));self.assertEqual(self.count('gqtp_deliveries'),1)
    def test_public_api_and_owner_receipt(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from gnosis_platform import gqtp_api as api
        from gnosis_platform.history_api import router
        from gnosis_platform.auth_api import authenticated
        req=self.begin();self.finish(req);cid=req['consultation_id'];g.checkpoint(self.db,self.key)
        app=FastAPI();app.include_router(router);app.dependency_overrides[authenticated]=lambda:{'account_id':self.account}
        with patch.object(api,'connect',lambda:connect(Path(self.tmp.name)/'db.sqlite')),TestClient(app) as c:
            response=c.get('/api/v1/transparency/checkpoints/1/events');self.assertEqual(response.status_code,200);self.assertNotIn(cid,response.text);self.assertNotIn('secret raw',response.text)
            self.assertEqual(c.get('/api/v1/transparency/checkpoints/1/file').content,g.canonical(g.checkpoint(self.db,self.key)))
            r=c.get('/api/v1/accounts/readings/'+cid+'/verification');self.assertEqual(r.status_code,200);self.assertEqual(r.headers['cache-control'],'no-store');self.assertTrue(g.verify_receipt(r.json(),self.pk))
            app.dependency_overrides[authenticated]=lambda:{'account_id':'other'}
            self.assertEqual(c.get('/api/v1/accounts/readings/'+cid+'/verification').status_code,404)
    def test_sticks_empty_casting_is_committed_and_delivered(self):
        g.enable_inventory_guard(self.db);sha,version=PROFILES['sticks'];meta=dict(mode='sticks',backend='ibm_marrakesh',external_job_id='sticks-test-123',circuit_sha256=sha,circuit_version=version,archive_sha256='f'*64,acquired_at='2026-11-18T04:07:37Z',submitted_at='2026-11-18T04:07:31Z',remote_measurements_match=True,qpu_seconds=2)
        raw=['0'*64]*18
        bid=import_batch(self.db,meta,[raw]*128,excluded=range(1,128))['batch_id'];g.note_qualification(self.db,bid,meta)
        m=g.register_batch(self.db,'sticks',bid,confirm_unrevealed=True);self.assertEqual(m['commercial_count'],1)
        self.assertNotEqual(g.measurement_id(meta['external_job_id'],0,'sticks'),g.measurement_id(meta['external_job_id'],1,'sticks'))
        n=g.checkpoint(self.db,self.key)['checkpoint']['tree_size'];g.release_batch(self.db,meta['external_job_id'],n,proof_sha256='e'*64,operator='mock test verification');approve(self.db,bid,operator='test',job_id=meta['external_job_id'],profile_sha=sha,confirm_unrevealed=True)
        req=self.begin('runes.sticks.quantum_past');self.assertEqual(run_claimed(self.db,req),'completed');g.checkpoint(self.db,self.key)
        rec=g.receipt(self.db,req['consultation_id']);self.assertTrue(g.verify_receipt(rec,self.pk));reading=json.loads(rec['saved_bytes']['reading_json']);self.assertEqual(len(reading['payload']['timeline']['frames']),73);self.assertEqual(reading['payload']['timeline']['final']['shown'],{})
    def test_key_is_private_and_no_overwrite(self):
        f=Path(self.tmp.name)/'key';pk=g.new_key(f);self.assertEqual(f.stat().st_mode&0o777,0o600);self.assertEqual(g.public_key(g.read_key(f)),pk)
        with self.assertRaises(FileExistsError):g.new_key(f)

if __name__=='__main__':unittest.main()
