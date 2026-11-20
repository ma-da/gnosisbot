import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from gnosis_platform import gqtp as g
from gnosis_platform.db import connect,migrate
from gnosis_platform.ibm_inventory import import_archive,approve_batch
from gnosis_platform.rune_past_inventory import import_batch,PROFILES
from gnosis_platform.public_inventory import snapshot

class PublicInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)
        self.db=connect(self.path/'db.sqlite');migrate(self.db)
        self.env=patch.dict(os.environ,{'GNOSIS_ENABLE_ACCOUNTS_API':'1','GNOSIS_ENABLE_IBM_PAST':'1','GNOSIS_ENABLE_RUNES':'1','GNOSIS_ENABLE_RUNE_PAST':'1'});self.env.start()
        self.key=Ed25519PrivateKey.generate();g.enable_inventory_guard(self.db)
    def tearDown(self):
        self.env.stop();self.db.close();self.temp.cleanup()
    def snap(self,engine='iching'):
        return next(x for x in snapshot(self.db,self.path)['engines'] if x['engine']==engine)
    def stock(self):
        meta=dict(backend='ibm_marrakesh',external_job_id='test-ibm-job',circuit_sha256='a'*64,circuit_version='test-v1',acquired_at='2026-11-18T04:07:37Z',submitted_at='2026-11-18T04:07:31Z')
        doc={'schema':'gnosis.ibm_past.v1','manifest':meta,'samples':[{'sample_index':i,'coin_bits':'0'*18,'moving_qpu_bits':'1'*6} for i in range(14)]}
        bid=import_archive(self.db,doc,file_sha256='b'*64)['batch_id'];g.note_qualification(self.db,bid,meta|{'mode':'iching','archive_sha256':'b'*64,'remote_measurements_match':True,'qpu_seconds':2});return bid
    def test_empty_and_quarantine_do_not_advertise_stock(self):
        self.stock();s=self.snap();self.assertEqual(s['counts']['available'],0);self.assertEqual(s['batch_count'],0)
    def test_demo_pending_timestamp_and_release(self):
        bid=self.stock();g.register_batch(self.db,'iching',bid,demo_count=12,confirm_unrevealed=True)
        s=self.snap();self.assertEqual(s['counts']['pending_release'],2);self.assertEqual(s['counts']['demo'],12);self.assertEqual(s['counts']['available'],0);self.assertEqual(s['check_counts']['signed'],0)
        env=g.checkpoint(self.db,self.key);n=env['checkpoint']['tree_size'];f=self.path/f'checkpoint-{n}.json';f.write_bytes(g.canonical(env));f.with_suffix('.json.ots').write_bytes(b'test-fixture-not-a-proof')
        s=self.snap();self.assertEqual(s['check_counts']['signed'],1);self.assertEqual(s['check_counts']['timestamp_submitted'],1);self.assertEqual(s['check_counts']['bitcoin_verified'],0)
        g.release_batch(self.db,'test-ibm-job',n,proof_sha256='c'*64,operator='mock test verification');self.assertEqual(self.snap()['counts']['available'],0)
        approve_batch(self.db,bid,operator='test',verified_job_id='test-ibm-job',verified_circuit_sha256='a'*64)
        s=self.snap();self.assertEqual(s['counts']['available'],2);self.assertEqual(s['check_counts']['released'],1)
        self.assertEqual(s['counts']['pending_release'],0)
        with patch.dict(os.environ,{'GNOSIS_ENABLE_IBM_PAST':'0'}):
            self.assertEqual(self.snap()['counts']['available'],0);self.assertEqual(self.snap()['counts']['approved_available'],2)
        public=json.dumps(s);self.assertNotIn('coin_bits',public);self.assertNotIn('nonce',public);self.assertNotIn('item_id',public);self.assertNotIn('consultation_id',public)
    def test_pouch_void_and_engine_separation(self):
        sha,version=PROFILES['pouch'];meta=dict(mode='pouch',backend='ibm_marrakesh',external_job_id='pouch-test-123',circuit_sha256=sha,circuit_version=version,archive_sha256='d'*64,acquired_at='2026-11-18T04:07:37Z',submitted_at='2026-11-18T04:07:31Z',remote_measurements_match=True,qpu_seconds=2)
        bid=import_batch(self.db,meta,[[0,0,0]]*124+[[31,0,0]]*4)['batch_id'];g.note_qualification(self.db,bid,meta);g.register_batch(self.db,'pouch',bid,confirm_unrevealed=True)
        c=self.snap('pouch')['counts'];self.assertEqual(c['committed'],128);self.assertEqual(c['pending_release'],124);self.assertEqual(c['excluded'],4);self.assertEqual(self.snap('sticks')['counts']['commercial'],0)
    def test_missing_or_changed_checkpoint_is_not_submitted(self):
        bid=self.stock();g.register_batch(self.db,'iching',bid,confirm_unrevealed=True);env=g.checkpoint(self.db,self.key);n=env['checkpoint']['tree_size'];f=self.path/f'checkpoint-{n}.json';f.write_text('changed');f.with_suffix('.json.ots').write_bytes(b'fixture');self.assertEqual(self.snap()['check_counts']['timestamp_submitted'],0)
