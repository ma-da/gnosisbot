"""Tests use synthetic proofs and mocked verifier responses, never external network."""
import hashlib, json, os, unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from gnosis_platform import admin_btc, gqtp as g
from gnosis_platform.rune_past_inventory import import_batch, PROFILES
from scripts import gqtp_verify_explorers as ex
import test_m5e_admin as fixtures

# Reuse fixture helpers without inheriting duplicate test methods.
class ReleaseTests(unittest.TestCase):
    setUp=fixtures.AdminTests.setUp;tearDown=fixtures.AdminTests.tearDown;stock=fixtures.AdminTests.stock;checkpoint=fixtures.AdminTests.checkpoint
    def fake(self,f,ok=True,explorer=False):
        info='File sha256 hash: '+hashlib.sha256(f.read_bytes()).hexdigest()+'\nverify BitcoinBlockHeaderAttestation(976388)\n'
        def run(args,**kw):
            if args[1]=='info':return SimpleNamespace(returncode=0,stdout=info,stderr='')
            return SimpleNamespace(returncode=0 if ok else 1,stdout=json.dumps({'height':976388,'confirmations_min':6}) if explorer else '',stderr='')
        return run
    def test_genesis_does_not_release_later_stock(self):
        n,f,p=self.checkpoint();self.stock()
        x=admin_btc.check(self.db,n,self.public,'ots',run=self.fake(f));self.assertEqual(x['status'],'bitcoin_verified');self.assertFalse(x['inventory_changed']);self.assertIsNone(self.db.execute('SELECT release_checkpoint FROM gqtp_batches').fetchone()[0])
    def test_withdrawn_and_failed_proof_stay_unavailable(self):
        bid=self.stock();n,f,p=self.checkpoint();x=admin_btc.check(self.db,n,self.public,'ots',run=self.fake(f,False));self.assertFalse(x['inventory_changed']);self.db.execute("UPDATE ibm_inventory_batches SET status='withdrawn' WHERE batch_id=?",(bid,));x=admin_btc.check(self.db,n,self.public,'ots',run=self.fake(f));self.assertFalse(x['inventory_changed']);self.assertEqual(self.db.execute('SELECT status FROM ibm_inventory_batches').fetchone()[0],'withdrawn')
    def test_explorer_release_and_method_recorded(self):
        self.stock();n,f,p=self.checkpoint()
        with patch.dict(os.environ,{'GNOSIS_BTC_VERIFIER':'explorers'}):
            x=admin_btc.check(self.db,n,self.public,'ots',run=self.fake(f,explorer=True));self.assertEqual(x['released_readings'],2);self.assertEqual(x['verification_method'],'ots_dual_explorer_headers')
        note=json.loads(self.db.execute('SELECT verification_note FROM gqtp_batches').fetchone()[0]);self.assertEqual(note['method'],'ots_dual_explorer_headers');self.assertEqual(note['evidence']['height'],976388)
    def test_all_three_engines_release_once_with_demo_and_invalid_preserved(self):
        self.stock()
        for engine,raw,excluded in [('pouch',[[0,0,0]]*124+[[31,0,0]]*4,()),('sticks',[['0'*64]*18]*128,range(1,128))]:
            sha,version=PROFILES[engine]
            meta=dict(mode=engine,backend='ibm_marrakesh',external_job_id=engine+'-auto-release-job',circuit_sha256=sha,circuit_version=version,archive_sha256=('d' if engine=='pouch' else 'e')*64,acquired_at='2026-11-18T04:07:37Z',submitted_at='2026-11-18T04:07:31Z',remote_measurements_match=True,qpu_seconds=2)
            bid=import_batch(self.db,meta,raw,excluded=excluded)['batch_id'];g.note_qualification(self.db,bid,meta);g.register_batch(self.db,engine,bid,confirm_unrevealed=True)
        n,f,p=self.checkpoint();x=admin_btc.check(self.db,n,self.public,'ots',run=self.fake(f));self.assertEqual(len(x['released_batches']),3);self.assertEqual(x['released_readings'],127)
        self.assertEqual(self.db.execute("SELECT count(*) FROM ibm_inventory_items WHERE state='void'").fetchone()[0],12)
        self.assertEqual(self.db.execute("SELECT count(*) FROM rune_inventory_items WHERE state='void'").fetchone()[0],131)
        self.assertEqual(self.db.execute("SELECT count(*) FROM rune_inventory_batches WHERE status='approved'").fetchone()[0],2)
        self.assertFalse(admin_btc.check(self.db,n,self.public,'ots',run=self.fake(f))['inventory_changed']);self.assertEqual(self.db.execute('SELECT count(*) FROM gqtp_events').fetchone()[0],n+3)
    def test_failure_rolls_back_check_and_release(self):
        self.stock();n,f,p=self.checkpoint();self.db.execute("CREATE TRIGGER force_failure BEFORE UPDATE OF status ON ibm_inventory_batches BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(Exception):admin_btc.check(self.db,n,self.public,'ots',run=self.fake(f))
        self.assertIsNone(self.db.execute('SELECT release_checkpoint FROM gqtp_batches').fetchone()[0]);self.assertEqual(self.db.execute('SELECT count(*) FROM gnosis_admin_btc_checks').fetchone()[0],0);self.assertEqual(self.db.execute('SELECT count(*) FROM gqtp_events').fetchone()[0],n)
    def test_file_change_during_check_blocks_release(self):
        self.stock();n,f,p=self.checkpoint();run=self.fake(f)
        def change(args,**kw):
            if args[1]!='info':p.write_bytes(b'changed')
            return run(args,**kw)
        with self.assertRaises(ValueError):admin_btc.check(self.db,n,self.public,'ots',run=change)
        self.assertIsNone(self.db.execute('SELECT release_checkpoint FROM gqtp_batches').fetchone()[0])

class HeaderTests(unittest.TestCase):
    # Bitcoin block 1 header replaced by known genesis header as a synthetic fixture
    # for hash/root/Pow math; fake provider height is not a live chain assertion.
    header=bytes.fromhex('01000000'+'00'*32+'3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a'+'29ab5f49ffff001d1dac2b7c')
    h='000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f'
    def test_agreement_and_exact_root(self):
        def fetch(base,path):return '100' if path.endswith('/height') else self.h if '/block-height/' in path else self.header.hex()
        root=self.header[36:68];self.assertTrue(ex.verify_header(self.header,self.h,root));self.assertEqual(ex.verify_paths([(1,root)],fetch=fetch)['block_hash'],self.h);self.assertIsNone(ex.verify_paths([(1,b'0'*32)],fetch=fetch))
    def test_disagreement_and_confirmation_threshold(self):
        def fetch(base,path):return '5' if path.endswith('/height') else self.h if '/block-height/' in path else self.header.hex()
        self.assertIsNone(ex.verify_paths([(1,self.header[36:68])],fetch=fetch))
        def disagree(base,path):return '100' if path.endswith('/height') else 'a'*64 if base==ex.BASES[1] and '/block-height/' in path else self.h if '/block-height/' in path else self.header.hex()
        self.assertIsNone(ex.verify_paths([(1,self.header[36:68])],fetch=disagree))
if __name__=='__main__':unittest.main()
