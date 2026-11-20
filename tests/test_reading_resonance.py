"""Offline regression tests using the actual account schema and cookie authentication."""
import hashlib, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gnosis_platform.db import connect,migrate
from gnosis_platform.account_hub_api import router
from gnosis_platform.research_export import export_jsonl

class ReadingResonanceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name)
        self.path=self.root/'test.sqlite3'
        env=patch.dict(os.environ,{'GNOSIS_DB_PATH':str(self.path),'GNOSIS_WEB_ORIGIN':'http://testserver'})
        env.start();self.addCleanup(env.stop)
        self.db=connect(self.path);self.addCleanup(self.db.close);migrate(self.db)
        self.now='2026-01-01T00:00:00Z'
        self.a='a'*64;self.b='b'*64;self.token='A'*43
        for account in (self.a,self.b):
            self.db.execute('INSERT INTO accounts(account_id) VALUES(?)',(account,))
            self.db.execute('INSERT INTO credit_accounts VALUES(?,50,0)',(account,))
        self.db.execute('INSERT INTO sessions(session_id,account_id,verifier_hash,created_at,expires_at) VALUES(?,?,?,?,?)',('session',self.a,hashlib.sha256(self.token.encode()).hexdigest(),self.now,'2099-01-01T00:00:00Z'))
        self.ids=['%032x'%i for i in range(1,7)]
        services=['iching.qrng_private','iching.quantum_past','runes.pouch.quantum_past','runes.sticks.classic','iching.quantum_future','iching.classic']
        for i,cid in enumerate(self.ids):
            app='runes' if services[i].startswith('runes') else 'iching'
            status='pending' if i==4 else 'completed'
            account=self.b if i==5 else self.a
            self.db.execute('INSERT INTO consultations(consultation_id,account_id,application_id,status,created_at,finished_at) VALUES(?,?,?,?,?,?)',(cid,account,app,status,self.now,self.now if status=='completed' else None))
            self.db.execute('INSERT INTO service_requests(request_id,consultation_id,service_id,provider,status,idempotency_key,credits_cost,started_at) VALUES(?,?,?,?,?,?,?,?)',('r'+cid,cid,services[i],'test',status,'k'+cid,0,self.now))
            if status=='completed':self.db.execute('INSERT INTO reading_results VALUES(?,?,?,?,?,?)',('result'+cid,cid,'v1','{"physical":"unchanged"}','{"hash":"original"}',self.now))
        app=FastAPI();app.include_router(router)
        self.client=TestClient(app);self.addCleanup(self.client.close)
        self.client.cookies.set('gnosis_session',self.token)
        self.origin={'Origin':'http://testserver'}
    def put(self,cid,value,headers=None):
        return self.client.put('/api/v1/accounts/readings/'+cid+'/resonance',json={'resonated':value},headers=self.origin if headers is None else headers)
    def items(self):
        res=self.client.get('/api/v1/accounts/hub');self.assertEqual(res.status_code,200,res.text)
        return {i['consultation_id']:i for i in res.json()['activity']['items']}
    def test_default_and_pending(self):
        items=self.items()
        self.assertEqual(items[self.ids[0]]['resonance'],{'resonated':False,'recorded':False,'updated_at':None})
        self.assertNotIn('resonance',items[self.ids[4]])
        self.assertNotIn(self.ids[5],items)
        self.assertEqual(self.db.execute('SELECT count(*) FROM reading_resonance').fetchone()[0],0)
    def test_toggle_persist_and_idempotence(self):
        cid=self.ids[0]
        r=self.put(cid,True);self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['resonated'])
        self.assertEqual(r.headers['cache-control'],'private, no-store');self.assertEqual(r.headers['x-robots-tag'],'noindex')
        self.assertEqual(r.json(),self.put(cid,True).json())
        first=self.db.execute('SELECT first_marked_at FROM reading_resonance').fetchone()[0]
        self.assertTrue(self.items()[cid]['resonance']['resonated'])
        r=self.put(cid,False);self.assertEqual(r.status_code,200);self.assertFalse(r.json()['resonated']);self.assertTrue(r.json()['recorded'])
        self.assertEqual(r.json(),self.put(cid,False).json());self.assertFalse(self.items()[cid]['resonance']['resonated'])
        self.put(cid,True);self.assertEqual(self.db.execute('SELECT first_marked_at FROM reading_resonance').fetchone()[0],first)
    def test_never_marked_is_not_negative(self):
        r=self.put(self.ids[0],False);self.assertEqual(r.status_code,200);self.assertFalse(r.json()['recorded'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM reading_resonance').fetchone()[0],0)
    def test_both_oracles(self):
        for cid in self.ids[:4]:self.assertEqual(self.put(cid,True).status_code,200)
        self.assertTrue(all(self.items()[cid]['resonance']['resonated'] for cid in self.ids[:4]))
    def test_owner_and_completed_only(self):
        for cid in (self.ids[4],self.ids[5],'f'*32,'bad'):
            self.assertEqual(self.put(cid,True).status_code,404)
        self.assertEqual(self.db.execute('SELECT count(*) FROM reading_resonance').fetchone()[0],0)
    def test_auth_origin_strict_type(self):
        self.assertEqual(self.put(self.ids[0],True,{'Origin':'https://elsewhere.example'}).status_code,403)
        self.assertEqual(self.put(self.ids[0],'true').status_code,422)
        self.assertEqual(self.put(self.ids[0],1).status_code,422)
        self.client.cookies.clear();self.assertEqual(self.put(self.ids[0],True).status_code,401)
    def test_only_feedback_table_changes(self):
        names=[r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('reading_resonance','sessions')")]
        def snapshot():return {n:[tuple(r) for r in self.db.execute('SELECT * FROM '+n)] for n in names}
        old=snapshot();self.put(self.ids[0],True);self.put(self.ids[0],False);self.assertEqual(snapshot(),old)
    def test_restricted_export(self):
        self.put(self.ids[0],True);self.put(self.ids[1],True);self.put(self.ids[1],False)
        out=self.root/'restricted.jsonl';manifest=export_jsonl(self.db,out)
        self.assertEqual(manifest['schema_version'],'gnosis.research.export.v2');self.assertEqual(manifest['classification'],'RESTRICTED_NOT_PUBLIC')
        rows={r['consultation_id']:r for r in map(json.loads,out.read_text().splitlines())}
        self.assertEqual(rows[self.ids[0]]['reading_resonated'],1);self.assertEqual(rows[self.ids[1]]['reading_resonated'],0)
        self.assertIsNone(rows[self.ids[2]]['reading_resonated']);self.assertIsNone(rows[self.ids[2]]['resonance_updated_at'])
        self.assertEqual(rows[self.ids[0]]['provenance'],{'hash':'original'})
        self.assertEqual(hashlib.sha256(out.read_bytes()).hexdigest(),manifest['sha256'])
        self.assertEqual(out.stat().st_mode&0o777,0o600)
