"""Real SQLite and shared API. QCI and NIST transport mocked; no paid jobs."""
import gzip,json,hashlib,os,tempfile,unittest
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
from gnosis_platform.consultations_api import router
from gnosis_platform.history_api import router as history
from gnosis_platform.account_hub_api import router as hub
from gnosis_platform import rune_production as rp
from gnosis_platform.transactions import begin_consultation,finish_request
from gnosis_platform.research import backfill

class RuneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite'
        self.db=connect(self.path);migrate(self.db)
        self.a=self.account();self.user={'account_id':self.a,'is_admin':True,'account_group':'standard','available':5,'reserved':0}
        self.db.execute("UPDATE accounts SET is_admin=1 WHERE account_id=?",(self.a,))
        grant(self.db,self.a,5,'tester','test',uuid4().hex)
        self.app=FastAPI()
        for r in (router,history,hub): self.app.include_router(r)
        self.app.dependency_overrides[authenticated]=lambda:self.user
        self.client=TestClient(self.app)
        self.env=patch.dict(os.environ,{'GNOSIS_ENABLE_RUNES':'1','GNOSIS_ENABLE_QCI':'1','QCI_API_TOKEN':'test-only',
          'GNOSIS_ENABLE_NIST':'1','GNOSIS_ENABLE_RUNE_NIST':'1','GNOSIS_ENABLE_CONSULTATION_SANDBOX':'1','GNOSIS_WEB_ORIGIN':''})
        self.env.start();self.addCleanup(self.env.stop)
        for m in ('consultations_api','history_api','account_hub_api','auth_api'):
            p=patch('gnosis_platform.'+m+'.connect',lambda:connect(self.path));p.start();self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup);self.addCleanup(self.db.close);self.addCleanup(self.client.close)
    def account(self):
        raw=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        return register(self.db,b64e(raw))['account_id']
    def body(self,source='classic',mode='pouch',key=None):
        return dict(service_id=f'runes.{mode}.{source}',idempotency_key=key or uuid4().hex,question='Test inquiry',inquiry_style='direct',research_publication_consent=False)
    def post(self,body): return self.client.post('/api/v1/consultations',json=body)
    def counts(self,table):return self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    def test_catalog_gates_and_disabled_ibm_even_in_sandbox(self):
        rows={x['service_id']:x for x in self.client.get('/api/v1/services/catalog').json()['services']}
        self.assertEqual(len([x for x in rows if x.startswith('runes.')]),10)
        for m in ('pouch','sticks'):
            for s in ('classic','qrng_private','qrng_public'): self.assertTrue(rows[f'runes.{m}.{s}']['available'])
            for s in ('quantum_past','quantum_future'):
                self.assertFalse(rows[f'runes.{m}.{s}']['available']);self.assertEqual(self.post(self.body(s,m)).status_code,503)
        with patch.dict(os.environ,{'GNOSIS_ENABLE_RUNES':'0'}):self.assertEqual(self.post(self.body()).status_code,503)
        self.assertEqual(self.counts('service_requests'),0)
    def test_classic_pouch_saved_replay_owner_hub_archive(self):
        body=self.body();res=self.post(body);self.assertEqual(res.status_code,200,res.text)
        data=res.json();cid=data['receipt']['consultation_id'];reading=data['result']['reading']
        self.assertEqual(reading['reading_id'],cid);self.assertEqual(len({x['rune_id'] for x in reading['payload']['draws']}),3)
        with patch.object(rp,'acquire',side_effect=AssertionError('recast')):
            self.assertEqual(self.post(body).json(),data)
            self.assertEqual(self.client.get('/api/v1/accounts/readings/'+cid).json()['reading'],reading)
        self.assertEqual(self.counts('rune_reading_facts'),1);self.assertEqual(self.counts('reading_facts'),0);self.assertEqual(backfill(self.db),0)
        raw=self.db.execute('SELECT archive_gzip,archive_sha256 FROM rune_private_archives').fetchone();dec=gzip.decompress(raw[0]);self.assertEqual(hashlib.sha256(dec).hexdigest(),raw[1])
        self.assertNotIn('raw_hex',res.text);self.assertNotIn('private_audit',res.text)
        hub=self.client.get('/api/v1/accounts/hub').json();self.assertIn('runes',[a['id'] for a in hub['applications']]);self.assertEqual(hub['activity']['items'][0]['open_url'],'/rune-oracle.html?reading='+cid)
        self.assertEqual(self.client.get('/api/v1/accounts/readings').json()['items'][0]['mode'],'pouch')
        self.assertEqual(tuple(self.db.execute('SELECT available,reserved FROM credit_accounts WHERE account_id=?',(self.a,)).fetchone()),(5,0))
        self.user['account_id']=self.account();self.assertEqual(self.client.get('/api/v1/accounts/readings/'+cid).status_code,404)
        self.assertEqual(self.client.get('/api/v1/consultations/'+cid).status_code,404)
        self.assertEqual(self.post(body).status_code,409)
    def test_qci_sticks_empty_valid_no_retry(self):
        with patch.object(rp.qci_qrng,'_access_token',return_value='fake'),patch.object(rp.qci_qrng,'_post',return_value=[0]*72) as post:
            data=self.post(self.body('qrng_private','sticks'));self.assertEqual(data.status_code,200,data.text)
            self.assertEqual(post.call_count,1);self.assertEqual(post.call_args.args[1]['n_samples'],72)
        r=data.json()['result']['reading'];p=r['payload'];self.assertEqual(len(p['casting']['chords']),72);self.assertEqual(p['casting']['degenerate_slots'],72);self.assertEqual(len(p['timeline']['frames']),73);self.assertEqual(p['timeline']['final']['shown'],{})
        self.assertEqual(r['source'],'qci');self.assertEqual(self.counts('rune_private_archives'),1)
    def test_qci_pouch_and_malformed_response(self):
        body=self.body('qrng_private');
        with patch.object(rp.qci_qrng,'_access_token',return_value='fake'),patch.object(rp.qci_qrng,'_post',return_value=[0]*12) as post:
            r=self.post(body);self.assertEqual(r.status_code,200,r.text);self.assertEqual(post.call_args.args[1]['n_bits'],16)
        body=self.body('qrng_private')
        with patch.object(rp.qci_qrng,'_access_token',return_value='fake'),patch.object(rp.qci_qrng,'_post',return_value=[True]*12) as post:
            r=self.post(body);self.assertEqual(r.status_code,502,r.text);self.assertEqual(self.post(body).status_code,502);self.assertEqual(post.call_count,1)
        self.assertEqual(self.counts('reading_results'),1);self.assertEqual(self.counts('rune_private_archives'),1)
    def test_claim_pending_staged_resume_and_forgery_rejected(self):
        body=self.body();req=begin_consultation(self.db,account_id=self.a,**body);rid=req['request_id']; stamp='2026-11-17T00:00:00Z'
        self.db.execute("INSERT INTO rune_executions VALUES(?,'claimed',?,NULL,?)",(rid,stamp,stamp))
        with patch.object(rp,'acquire',side_effect=AssertionError('duplicate provider call')):
            p=self.post(body);self.assertEqual(p.status_code,202,p.text);self.assertEqual(self.client.get('/api/v1/consultations/'+req['consultation_id']).json()['status'],'pending')
        stage=rp.acquire(body['service_id'],rid);self.db.execute("UPDATE rune_executions SET status='staged',staged_json=? WHERE request_id=?",(rp.packed(stage),rid))
        r,pr,priv=rp.build_reading(body['service_id'],req['consultation_id'],stage);r['payload']['draws'][0]['name']='not authentic'
        with self.assertRaises(ValueError):finish_request(self.db,rid,success=True,result_json=r,provenance_json=pr,private_rune_archive=priv,schema_version='rune-reading-v0')
        self.assertEqual(self.counts('reading_results'),0)
        with patch.object(rp,'acquire',side_effect=AssertionError('duplicate provider call')):
            self.assertEqual(self.post(body).status_code,200)
        self.assertEqual(self.counts('reading_results'),1)
    def test_nist_derived_deterministic(self):
        p={'provider':'nist','beacon_output_value':'12'*64,'beacon_timestamp':'2026-11-17T00:00:00Z','signature_verified_locally':False}
        with patch.object(rp.nist_beacon,'cast',return_value=({},p)):
            body=self.body('qrng_public');res=self.post(body);self.assertEqual(res.status_code,200,res.text)
            pr=res.json()['result']['provenance'];self.assertFalse(pr['independent_entropy_per_consultation']);self.assertTrue(pr['public_beacon'])
            raw=hashlib.shake_256(bytes.fromhex(pr['derivation_domain_hex'])+bytes.fromhex(p['beacon_output_value'])+bytes.fromhex(pr['derivation_request_id'])).digest(24)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),pr['entropy_sha256'])
    def test_no_auth_no_cast_and_origin_guard(self):
        self.app.dependency_overrides.clear();self.assertEqual(self.post(self.body()).status_code,401)
        self.app.dependency_overrides[authenticated]=lambda:self.user
        self.assertEqual(self.client.post('/api/v1/consultations',json=self.body(),headers={'Origin':'https://evil.invalid'}).status_code,403)
        self.assertEqual(self.counts('service_requests'),0)
    def test_zero_credit_qci_rejected_classic_allowed(self):
        self.db.execute('UPDATE credit_accounts SET available=0 WHERE account_id=?',(self.a,))
        self.assertEqual(self.post(self.body('qrng_private')).status_code,402);self.assertEqual(self.post(self.body()).status_code,200)
    def test_real_session_cookie_and_shared_cooldown(self):
        import secrets
        token=secrets.token_urlsafe(32)
        self.db.execute("UPDATE accounts SET is_admin=0 WHERE account_id=?",(self.a,))
        self.db.execute("INSERT INTO sessions(session_id,account_id,verifier_hash,created_at,expires_at) VALUES(?,?,?,?,?)",
            (uuid4().hex,self.a,hashlib.sha256(token.encode()).hexdigest(),'2026-01-01T00:00:00Z','2099-01-01T00:00:00Z'))
        self.app.dependency_overrides.clear()
        self.client.cookies.set('gnosis_session',token)
        body=self.body();r=self.post(body);self.assertEqual(r.status_code,200,r.text)
        cid=r.json()['receipt']['consultation_id']
        self.assertEqual(self.post(self.body('qrng_private')).status_code,429)
        self.assertEqual(self.post(body).status_code,200)
        for path in ('/api/v1/accounts/readings/','/api/v1/consultations/'):
            saved=self.client.get(path+cid);self.assertEqual(saved.status_code,200);self.assertEqual(saved.headers['Cache-Control'],'no-store')
        self.client.cookies.clear();self.assertEqual(self.client.get('/api/v1/accounts/readings/'+cid).status_code,401)
    def test_classic_sticks_full_chronology(self):
        r=self.post(self.body(mode='sticks'));self.assertEqual(r.status_code,200,r.text)
        p=r.json()['result']['reading']['payload'];self.assertEqual(len(p['casting']['chords']),72);self.assertEqual(len(p['timeline']['frames']),73)
        self.assertNotIn('raw_bitstrings_msb_first',p['casting'])

if __name__=='__main__': unittest.main()
