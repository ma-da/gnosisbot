import hashlib,json,os,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from gnosis_platform import gqtp as g, admin_api,admin_metrics as m,admin_btc
from gnosis_platform.db import connect,migrate
from gnosis_platform.auth_api import authenticated

class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.env=patch.dict(os.environ,{'GNOSIS_DATA_DIR':str(self.path),'GNOSIS_DB_PATH':str(self.path/'db.sqlite'),'GNOSIS_ENABLE_ADMIN_DASHBOARD':'1','GNOSIS_ENABLE_ACCOUNTS_API':'1','GNOSIS_IBM_REQUEST_OVERHEAD_SECONDS':'2','GNOSIS_WEB_ORIGIN':'','GNOSIS_BTC_VERIFIER':'core'});self.env.start();self.db=connect();migrate(self.db);self.public=self.path/'transparency'/'public';self.public.mkdir(parents=True)
    def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()
    def reading(self,cid,sid,finished,status='completed'):
        self.db.execute('INSERT INTO consultations(consultation_id,application_id,question,status,created_at,finished_at) VALUES(?,?,?,?,?,?)',(cid,'runes' if sid.startswith('runes.') else 'iching','PRIVATE QUESTION',status,finished,finished))
        self.db.execute('INSERT INTO service_requests(request_id,consultation_id,service_id,status,idempotency_key,credits_cost,started_at,completed_at) VALUES(?,?,?,?,?,?,?,?)',(cid+'r',cid,sid,status,cid+'key',0,finished,finished))
        if status=='completed':self.db.execute('INSERT INTO reading_results VALUES(?,?,?,?,?,?)',(cid+'res',cid,'test','PRIVATE READING','PRIVATE PROVENANCE',finished))
    def stock(self):
        from gnosis_platform.ibm_inventory import import_archive
        meta=dict(backend='ibm_marrakesh',external_job_id='test-job',circuit_sha256='a'*64,circuit_version='test-v1',acquired_at='2026-11-18T04:07:37Z',submitted_at='2026-11-18T04:07:31Z')
        doc={'schema':'gnosis.ibm_past.v1','manifest':meta,'samples':[{'sample_index':i,'coin_bits':'0'*18,'moving_qpu_bits':'1'*6} for i in range(14)]}
        bid=import_archive(self.db,doc,file_sha256='b'*64)['batch_id'];g.note_qualification(self.db,bid,meta|{'mode':'iching','archive_sha256':'b'*64,'remote_measurements_match':True,'qpu_seconds':2,'resource_units':0.02893});g.enable_inventory_guard(self.db);g.register_batch(self.db,'iching',bid,demo_count=12,confirm_unrevealed=True);return bid
    def checkpoint(self):
        key=Ed25519PrivateKey.generate();env=g.checkpoint(self.db,key);n=env['checkpoint']['tree_size'];f=self.public/f'checkpoint-{n}.json';f.write_bytes(g.canonical(env));p=f.with_suffix('.json.ots');p.write_bytes(b'fake proof for mocked client');(self.public/'public-key.txt').write_text(g.public_key(key)+'\n');return n,f,p
    def test_daily_once_per_completed_saved_reading_and_private_data_absent(self):
        self.reading('a','iching.qrng_private','2026-11-17T04:00:00Z');self.reading('b','runes.pouch.classic','2026-11-18T04:00:00Z');self.reading('c','iching.qrng_private','2026-11-18T04:00:00Z','pending')
        self.db.execute("INSERT INTO service_requests(request_id,consultation_id,service_id,status,idempotency_key,credits_cost,started_at) VALUES('extra','a','iching.ai_enhancement','completed','extra-key',1,'2026-11-17T05:00:00Z')")
        out=m.reading_counts(self.db,3,datetime(2026,11,18,tzinfo=timezone.utc));self.assertEqual(out['total'],2);self.assertEqual(out['period_total'],2);self.assertEqual([sum(s['daily'][i] for s in out['series']) for i in range(3)],[0,1,1]);self.assertNotIn('PRIVATE',json.dumps(m.overview(self.db)))
    def test_inventory_billing_proxy_and_measurement_override(self):
        self.stock();b=m.ibm_summary(self.db);j=b['jobs'][0];self.assertEqual(j['actual_seconds'],2);self.assertEqual(j['commercial'],2);self.assertIsNone(j['measured_seconds']);self.assertEqual(j['estimated_seconds'],4);self.assertEqual(j['planning_basis'],'reported_charge_proxy');self.assertEqual(b['inventory']['actual_per_reading'],1)
        self.db.execute('INSERT INTO gnosis_admin_ibm_usage VALUES(?,?,?,?)',('test-job',2,m.stamp(),'final'));self.db.execute('INSERT INTO gnosis_admin_ibm_timing VALUES(?,?,?,?)',('test-job',0.04,m.stamp(),'measured circuit time'));b=m.ibm_summary(self.db);self.assertEqual(b['totals']['requests'],1);self.assertEqual(b['totals']['actual_seconds'],2);self.assertAlmostEqual(b['totals']['estimated_seconds'],2.04);self.assertEqual(b['jobs'][0]['planning_basis'],'measured');self.assertEqual(m.overview(self.db)['inventory']['engines'][0]['counts']['available'],0)
    def test_unknown_metrics_not_zero_and_snapshots(self):
        d=m.overview(self.db);self.assertIsNone(d['ibm']['totals']['actual_seconds']);self.assertEqual(d['contacts']['status'],'not_configured');self.assertIsNone(d['stripe']['net_minor']);m.store_snapshot(self.db,'contacts',{'status':'reported','count':0});self.assertEqual(m.get_snapshot(self.db,'contacts')['count'],0)
    def test_proof_check_releases_qualified_stock_and_changed_proof_stale(self):
        self.stock();n,f,p=self.checkpoint();digest=hashlib.sha256(f.read_bytes()).hexdigest();info=f'File sha256 hash: {digest}\nverify BitcoinBlockHeaderAttestation(976388)\n'
        result=lambda code,stdout='': SimpleNamespace(returncode=code,stdout=stdout,stderr='')
        # Mere attestation is not independent verification.
        with patch('os.environ',dict(os.environ)):
            x=admin_btc.check(self.db,n,self.public,'ots',run=lambda args,**kw:result(0,info) if args[1]=='info' else result(1));self.assertEqual(x['status'],'attestation_present_not_verified')
            x=admin_btc.check(self.db,n,self.public,'ots',run=lambda args,**kw:result(0,info) if args[1]=='info' else result(0));self.assertEqual(x['status'],'bitcoin_verified');self.assertTrue(x['inventory_changed']);self.assertEqual(x['released_readings'],2)
            again=admin_btc.check(self.db,n,self.public,'ots',run=lambda args,**kw:result(0,info) if args[1]=='info' else result(0));self.assertFalse(again['inventory_changed'])
        self.assertEqual(self.db.execute('SELECT release_checkpoint FROM gqtp_batches').fetchone()[0],n);self.assertEqual(self.db.execute('SELECT status FROM ibm_inventory_batches').fetchone()[0],'approved');self.assertEqual(m.proof_state(self.db,self.public)[0]['status'],'bitcoin_verified');p.write_bytes(b'changed');self.assertEqual(m.proof_state(self.db,self.public)[0]['status'],'proof_saved_not_checked')
    def test_pending_wrong_digest_and_guarded_admin_routes(self):
        n,f,p=self.checkpoint();digest=hashlib.sha256(f.read_bytes()).hexdigest();stub=lambda args,**kw:SimpleNamespace(returncode=0,stdout=f'File sha256 hash: {digest}\nPendingAttestation',stderr='')
        self.assertEqual(admin_btc.check(self.db,n,self.public,'ots',run=stub)['status'],'pending_attestation')
        stub=lambda args,**kw:SimpleNamespace(returncode=0,stdout='File sha256 hash: '+'a'*64+'\nBitcoinBlockHeaderAttestation(8)',stderr='')
        self.assertEqual(admin_btc.check(self.db,n,self.public,'ots',run=stub)['status'],'proof_checkpoint_mismatch')
        app=FastAPI();app.include_router(admin_api.router);c=TestClient(app)
        self.assertEqual(c.get('/admin/').status_code,401);self.assertEqual(c.get('/api/v1/admin/overview').status_code,401)
        app.dependency_overrides[authenticated]=lambda:{'is_admin':0};self.assertEqual(c.get('/admin/').status_code,403);self.assertEqual(c.post(f'/api/v1/admin/transparency/{n}/check').status_code,403)
        app.dependency_overrides[authenticated]=lambda:{'is_admin':1};self.assertEqual(c.get('/admin/').status_code,200);self.assertEqual(c.get('/admin/dashboard.js').status_code,200);r=c.get('/api/v1/admin/overview');self.assertEqual(r.status_code,200);self.assertIn('no-store',r.headers['cache-control']);self.assertEqual(c.post(f'/api/v1/admin/transparency/{n}/check',headers={'Origin':'https://other.example'}).status_code,403)
        with patch.dict(os.environ,{'GNOSIS_ENABLE_ADMIN_DASHBOARD':'0'}):self.assertEqual(c.get('/api/v1/admin/overview').status_code,403)
