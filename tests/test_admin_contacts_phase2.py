"""Isolated Phase 2 tests: no production DB, no Resend traffic."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gnosis_platform.db import connect, migrate
from gnosis_platform import site_contacts, contact_protection
from gnosis_platform.site_contact_api import router as public_router
from gnosis_platform.admin_contacts_api import router as private_router, EmailMessage, perform_send
from gnosis_platform.auth_api import authenticated

class FakeHTTP:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):return b'{"id":"resend-stub-123"}'

class ContactPhase2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{
            'GNOSIS_DATA_DIR':self.temp.name,'GNOSIS_DB_PATH':str(Path(self.temp.name)/'test.db'),
            'GNOSIS_CONTACT_MIN_SECONDS':'16',
            'GNOSIS_CONTACT_TOKEN_TTL_SECONDS':'3600',
            'GNOSIS_CONTACT_EMAIL_PER_DAY':'3',
            'GNOSIS_CONTACT_GLOBAL_PER_HOUR':'60',
            'GNOSIS_ENABLE_NATIVE_CONTACTS':'1','GNOSIS_CONTACT_ENCRYPTION_KEY':Fernet.generate_key().decode(),
            'GNOSIS_WEB_ORIGIN':'https://gnosis.bot','GNOSIS_ENABLE_ADMIN_DASHBOARD':'1',
            'GNOSIS_ENABLE_ADMIN_RESEND_SEND':'NO','RESEND_API_KEY':'re_stub',
        });self.env.start()
        self.db=connect();migrate(self.db)
        self.db.execute("INSERT INTO accounts(account_id,is_admin) VALUES('admin-fixture',1)")
        app=FastAPI();app.include_router(public_router);app.include_router(private_router)
        self.client=TestClient(app);self.app=app
    def tearDown(self):
        self.client.close();self.db.close();self.env.stop();self.temp.cleanup()
    def post_contact(self, data, headers):
        # Simulate a form opened 17 seconds earlier.
        # Real production timing enforcement remains unchanged.
        with patch.object(
            contact_protection,
            'now_ms',
            return_value=contact_protection.now_ms()-17000
        ):
            response = self.client.post(
                '/api/v1/contact/token',
                headers={'Origin':'https://gnosis.bot'}
            )

        self.assertEqual(response.status_code, 200)

        return self.client.post(
            '/api/v1/contact',
            json={**data, 'token':response.json()['token']},
            headers=headers
        )

    def test_public_rejects_cross_origin_invalid_and_stores_encrypted(self):
        data={'name':'Ada','email':'ada@example.com','message':'A private message'}
        self.assertEqual(self.post_contact(data=data,headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.post_contact(data={**data,'message':''},headers={'Origin':'https://gnosis.bot'}).status_code,422)
        self.assertEqual(self.post_contact(data=data,headers={'Origin':'https://gnosis.bot'}).status_code,200)
        raw=self.db.execute('SELECT * FROM gnosis_site_contact_messages').fetchone()
        self.assertNotIn(b'private',raw['message_ciphertext'])
        self.assertNotIn(b'ada@example.com',raw['email_ciphertext'])
        self.assertEqual(site_contacts.counts(self.db),{'total':1,'unread':1,'quarantine':0})
        self.assertEqual(site_contacts.list_messages(self.db)['messages'][0]['message'],'A private message')
    def test_admin_only_read_and_origins_for_mutation(self):
        self.post_contact(data={'name':'Ada','email':'ada@example.com','message':'hi'},headers={'Origin':'https://gnosis.bot'})
        self.assertEqual(self.client.get('/api/v1/admin/contact-messages').status_code,401)
        self.app.dependency_overrides[authenticated]=lambda:{'is_admin':0,'account_id':'admin-fixture'}
        self.assertEqual(self.client.get('/api/v1/admin/contact-messages').status_code,403)
        self.app.dependency_overrides[authenticated]=lambda:{'is_admin':1,'account_id':'admin-fixture'}
        results=self.client.get('/api/v1/admin/contact-messages')
        self.assertEqual(results.status_code,200)
        self.assertIn('no-store',results.headers['cache-control'])
        mid=results.json()['messages'][0]['id']
        path=f'/api/v1/admin/contact-messages/{mid}/state'
        self.assertEqual(self.client.post(path,json={'action':'mark_read'},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post(path,json={'action':'mark_read'},headers={'Origin':'https://gnosis.bot'}).status_code,200)
        self.assertEqual(site_contacts.counts(self.db)['unread'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM gnosis_admin_contact_audit').fetchone()[0],1)
        self.assertEqual(self.client.post(path,json={'action':'mark_read'},headers={'Origin':'https://gnosis.bot'}).json()['changed'],False)
    def test_rate_limit_honeypot_and_manual_mail_gate(self):
        headers={'Origin':'https://gnosis.bot'}
        data={'name':'Ada','email':'ada@example.com','message':'some thoughts'}
        self.assertEqual(self.post_contact(data={**data,'website':'spam'},headers=headers).status_code,200)
        self.assertEqual(site_contacts.counts(self.db)['total'],0)
        for _ in range(3):self.assertEqual(self.post_contact(data=data,headers=headers).status_code,200)
        self.assertEqual(self.post_contact(data=data,headers=headers).status_code,429)
        with self.assertRaises(RuntimeError):
            perform_send(self.db,actor='admin-fixture',body=EmailMessage(from_address='support@gnosis.bot',to_address='test@example.com',subject='Test',message='Hello'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM gnosis_admin_manual_emails').fetchone()[0],0)
    def test_manual_email_is_audited_once_and_requires_domain(self):
        body=EmailMessage(from_address='support@gnosis.bot',to_address='test@example.com',subject='Test',message='Hello')
        with patch.dict(os.environ,{'GNOSIS_ENABLE_ADMIN_RESEND_SEND':'YES'}):
            with self.assertRaises(ValueError):
                perform_send(self.db,actor='admin-fixture',body=body.model_copy(update={'from_address':'other@evil.test'}))
            out=perform_send(self.db,actor='admin-fixture',body=body,transport=lambda *args,**kwargs:FakeHTTP())
            self.assertEqual(out['status'],'sent')
        record=self.db.execute('SELECT * FROM gnosis_admin_manual_emails').fetchone()
        self.assertEqual(record['status'],'sent')
        self.assertEqual(record['provider_message_id'],'resend-stub-123')
        self.assertNotIn(b'test@example.com',record['to_ciphertext'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM gnosis_admin_manual_emails').fetchone()[0],1)

if __name__=='__main__':unittest.main()
