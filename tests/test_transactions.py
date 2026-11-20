"""Milestone 2A: real SQLite transactions, no external provider calls."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect, migrate
from gnosis_platform.identity import register, grant, b64e
from gnosis_platform.transactions import (
    begin_consultation, finish_request, CooldownActive, InsufficientCredits, RequestConflict
)

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'test.db')
        migrate(self.db)
        key=Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(key))['account_id']
        grant(self.db,self.account,20,'test_admin','test',uuid4().hex)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def begin(self, service='iching.quantum_future', idem=None, **kw):
        return begin_consultation(self.db, account_id=self.account,service_id=service,
                                  idempotency_key=idem or uuid4().hex,**kw)

    def balance(self):
        r=self.db.execute('SELECT available,reserved FROM credit_accounts WHERE account_id=?',(self.account,)).fetchone()
        return (r['available'],r['reserved'])

    def test_reserve_settle_exactly_once(self):
        token=uuid4().hex
        r=self.begin(idem=token,question='A question')
        self.assertEqual(self.balance(),(10,10))
        again=self.begin(idem=token,question='A question')
        self.assertEqual(again['request_id'],r['request_id'])
        with self.assertRaises(RequestConflict):
            self.begin(idem=token,question='Different')
        completed=finish_request(self.db,r['request_id'],success=True,
              result_json={'lines':[6,7,8,9,7,8]},provenance_json={'backend':'test'})
        self.assertEqual(completed['status'],'completed')
        finish_request(self.db,r['request_id'],success=True,
              result_json={'lines':[9]*6},provenance_json={'backend':'test'})
        self.assertEqual(self.balance(),(10,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM reading_results').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT kind,count(*) FROM credit_ledger GROUP BY kind').fetchall()[-1]['kind'],'settle')
        with self.assertRaises(RequestConflict):
            finish_request(self.db,r['request_id'],success=False)

    def test_cooldown_and_failure_refund(self):
        r=self.begin(service='iching.quantum_past')
        self.assertEqual(self.balance(),(15,5))
        with self.assertRaises(CooldownActive):
            self.begin(service='iching.qrng_private')
        failed=finish_request(self.db,r['request_id'],success=False)
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(self.balance(),(20,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM cooldowns').fetchone()[0],0)
        r2=self.begin(service='iching.qrng_private')
        self.assertEqual(r2['credits_cost'],0)
        self.assertEqual(self.balance(),(20,0))

    def test_admin_bypasses_cooldown_but_not_credits(self):
        self.db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.account,))
        a=self.begin(service='iching.quantum_future')
        b=self.begin(service='iching.quantum_future')
        self.assertNotEqual(a['request_id'],b['request_id'])
        self.assertEqual(self.balance(),(0,20))
        with self.assertRaises(InsufficientCredits):
            self.begin(service='iching.quantum_future')

    def test_zero_cost_requires_one_credit(self):
        self.db.execute('UPDATE credit_accounts SET available=0 WHERE account_id=?',(self.account,))
        with self.assertRaises(InsufficientCredits):
            self.begin(service='iching.qrng_public')
        self.assertEqual(self.db.execute('SELECT count(*) FROM service_requests').fetchone()[0],0)

    def test_transaction_rollback_and_new_connection_idempotency(self):
        idem=uuid4().hex
        r=self.begin(service='iching.quantum_past',idem=idem)
        with connect(Path(self.tmp.name)/'test.db') as other:
            same=begin_consultation(other,account_id=self.account,
              service_id='iching.quantum_past',idempotency_key=idem)
            self.assertEqual(same['request_id'],r['request_id'])
        self.assertEqual(self.balance(),(15,5))

if __name__=='__main__':unittest.main()
