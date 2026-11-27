import os, tempfile, unittest, json, re
from pathlib import Path
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gnosis_platform.db import connect,migrate
from gnosis_platform.site_contact_api import router
from gnosis_platform.admin_contacts_api import router as admin_router
from gnosis_platform.admin_api import require_admin
from gnosis_platform.site_contacts import list_messages,change_state
from gnosis_platform import contact_protection as protection

class ContactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'GNOSIS_DB_PATH':str(Path(self.tmp.name)/'db.sqlite3'),'GNOSIS_ENABLE_NATIVE_CONTACTS':'1','GNOSIS_CONTACT_ENCRYPTION_KEY':Fernet.generate_key().decode(),'GNOSIS_WEB_ORIGIN':'https://gnosis.bot','GNOSIS_CONTACT_MIN_SECONDS':'16','GNOSIS_CONTACT_TOKEN_TTL_SECONDS':'3600','GNOSIS_CONTACT_EMAIL_PER_DAY':'3','GNOSIS_CONTACT_GLOBAL_PER_HOUR':'60','GNOSIS_CONTACT_QUARANTINE_DAYS':'14'});self.env.start();self.addCleanup(self.env.stop)
        self.origin={'Origin':'https://gnosis.bot'}
        self.app=FastAPI();self.app.include_router(router);self.app.include_router(admin_router);self.client=TestClient(self.app)
        with closing(connect()) as db:migrate(db);db.execute("INSERT INTO accounts(account_id,is_admin) VALUES('admin',1)")
    def token(self,age=17):
        with patch.object(protection,'now_ms',return_value=protection.now_ms()-age*1000):
            response=self.client.post('/api/v1/contact/token',headers=self.origin)
        self.assertEqual(response.status_code,200);return response.json()['token']
    def body(self,**changes):return {'name':'Visitor','email':'visitor@example.org','message':'Question about quantum research','website':'','token':self.token(),**changes}
    def post(self,body,**kw):return self.client.post('/api/v1/contact',json=body,headers=self.origin,**kw)
    def test_timing_and_replay(self):
        body=self.body(token=self.token(0));r=self.post(body);self.assertEqual(r.status_code,425);self.assertGreater(r.json()['retry_after'],0)
        with patch('gnosis_platform.site_contacts.now_ms',return_value=protection.now_ms()+16000):self.assertEqual(self.post(body).status_code,200)
        with patch('gnosis_platform.site_contacts.now_ms',return_value=protection.now_ms()+16000):self.assertEqual(self.post(body).status_code,409)
        with closing(connect()) as db:self.assertEqual(len(list_messages(db)['messages']),1)
    def test_forged_expired_missing_and_origin(self):
        t=self.token();self.assertEqual(self.post(self.body(token=t[:-1]+('0' if t[-1]!='0' else '1'))).status_code,403)
        self.assertEqual(self.post(self.body(token=self.token(3601))).status_code,403)
        self.assertEqual(self.post(self.body(token='')).status_code,403)
        self.assertEqual(self.client.post('/api/v1/contact',json=self.body(),headers={'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/contact/token').status_code,403)
    def test_body_limit_and_duplicate_fields(self):
        self.assertEqual(self.post(self.body(message='x'*8192)).status_code,413)
        self.assertEqual(self.post(self.body(message='x'*4001)).status_code,422)
        self.assertEqual(self.post(self.body(message='界'*3000)).status_code,413)
        r=self.client.post('/api/v1/contact',content=b'{"name":"A","name":"B"}',headers={**self.origin,'Content-Type':'application/json'});self.assertEqual(r.status_code,422)
        chunks=(b'x'*4096 for _ in range(3));r=self.client.post('/api/v1/contact',content=chunks,headers={**self.origin,'Content-Type':'application/json'});self.assertEqual(r.status_code,413)
    def test_honeypot_and_encryption(self):
        self.assertEqual(self.post(self.body(website='spam')).status_code,200)
        self.assertEqual(self.post(self.body()).status_code,200)
        with closing(connect()) as db:
            row=db.execute('SELECT * FROM gnosis_site_contact_messages').fetchone();self.assertNotIn(b'Question',row['message_ciphertext']);self.assertNotIn('visitor',row['email_digest']);self.assertEqual(list_messages(db)['spam']['rejected'],1)
    def test_rate_limits_and_deletion(self):
        for _ in range(3):self.assertEqual(self.post(self.body()).status_code,200)
        self.assertEqual(self.post(self.body()).status_code,429)
        with closing(connect()) as db:
            mid=list_messages(db)['messages'][0]['id'];change_state(db,message_id=mid,actor_account_id='admin',action='delete')
        self.assertEqual(self.post(self.body()).status_code,429)
        with patch.dict(os.environ,{'GNOSIS_CONTACT_GLOBAL_PER_HOUR':'3'}):self.assertEqual(self.post(self.body(email='different@example.org')).status_code,429)
    def test_quarantine_release_and_prune(self):
        self.assertEqual(self.post(self.body(message='We offer SEO services and backlinks')).status_code,200)
        with closing(connect()) as db:
            self.assertEqual(list_messages(db)['counts']['total'],0);q=list_messages(db,quarantine=True);self.assertEqual(q['counts']['quarantine'],1)
            change_state(db,message_id=q['messages'][0]['id'],actor_account_id='admin',action='release');self.assertEqual(list_messages(db)['counts']['unread'],1)
        self.assertEqual(self.post(self.body(email='two@example.org',message='http://a.example http://b.example http://c.example')).status_code,200)
        with closing(connect()) as db:
            db.execute("UPDATE gnosis_site_contact_messages SET created_at='2000-01-01T00:00:00.000Z' WHERE quarantine_reason IS NOT NULL")
            self.assertEqual(list_messages(db,quarantine=True)['counts']['quarantine'],0)
            self.assertEqual(db.execute('SELECT length(message_ciphertext) FROM gnosis_site_contact_messages WHERE deleted_at IS NOT NULL').fetchone()[0],0)
    def test_no_js_and_escaping(self):
        r=self.client.get('/api/v1/contact/form');self.assertEqual(r.status_code,200);self.assertIn('no-store',r.headers['cache-control']);self.assertIn('form-action',r.headers['content-security-policy'])
        t=re.search(r'name="token" value="([^"]+)"',r.text).group(1)
        r=self.client.post('/api/v1/contact',data=self.body(token=t,message='</textarea><script>alert(1)</script>'),headers=self.origin);self.assertEqual(r.status_code,425);self.assertNotIn('<script>alert',r.text);self.assertIn('&lt;script&gt;',r.text)
        r=self.client.post('/api/v1/contact',data=self.body(),headers=self.origin);self.assertEqual(r.status_code,200);self.assertIn('Message received',r.text)
    def test_atomic_concurrent_replay(self):
        body=self.body()
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.post(body).status_code,range(4)))
        self.assertEqual(sorted(results),[200,409,409,409])
    def test_admin_quarantine_protected(self):
        self.assertEqual(self.post(self.body(message='We offer SEO services and backlinks')).status_code,200)
        self.assertIn(self.client.get('/api/v1/admin/contact-messages?quarantine=true').status_code,(401,403))
        self.app.dependency_overrides[require_admin]=lambda:{'account_id':'admin','is_admin':1}
        normal=self.client.get('/api/v1/admin/contact-messages').json();self.assertEqual(normal['messages'],[])
        q=self.client.get('/api/v1/admin/contact-messages?quarantine=true').json();self.assertEqual(len(q['messages']),1)
        mid=q['messages'][0]['id'];path='/api/v1/admin/contact-messages/'+mid+'/state'
        self.assertEqual(self.client.post(path,json={'action':'release'},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post(path,json={'action':'release'},headers=self.origin).status_code,200)
        self.assertEqual(self.client.get('/api/v1/admin/contact-messages').json()['counts']['unread'],1)
    def test_exact_timing_boundary(self):
        from gnosis_platform.contact_protection import verify, AdmissionError
        start=protection.now_ms()
        with patch.object(protection,'now_ms',return_value=start): t=protection.issue()['token']
        with self.assertRaises(AdmissionError):verify(t,start+15999)
        self.assertEqual(len(verify(t,start+16000)),2)
    def test_disabled(self):
        with patch.dict(os.environ,{'GNOSIS_ENABLE_NATIVE_CONTACTS':'0'}):self.assertEqual(self.client.post('/api/v1/contact/token',headers=self.origin).status_code,503);self.assertEqual(self.post({'name':'x'}).status_code,503)
if __name__=='__main__':unittest.main()
