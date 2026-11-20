"""Milestone 2C: durable admission order and credit accounting under concurrency."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect, migrate
from gnosis_platform.identity import register, grant, b64e
from gnosis_platform.credit_view import credit_view
from gnosis_platform.transactions import begin_consultation, finish_request, InsufficientCredits


class AdmissionLocksTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'credits.db'
        self.db=connect(self.path)
        migrate(self.db)
        raw=Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.account=register(self.db,b64e(raw))['account_id']
        grant(self.db,self.account,15,'test','m2c',uuid4().hex)
        self.db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.account,))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def snapshot(self):
        return credit_view(self.db.execute('SELECT * FROM credit_accounts WHERE account_id=?',(self.account,)).fetchone())

    def submit(self, key):
        with closing(connect(self.path)) as db:
            try:
                r=begin_consultation(db,account_id=self.account,service_id='iching.quantum_future',idempotency_key=key)
                return 'accepted',r
            except InsufficientCredits:
                return 'rejected',None

    def test_concurrent_admission_prevents_overcommit(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(self.submit, [uuid4().hex for _ in range(4)]))
        accepted=[r for status,r in results if status=='accepted']
        self.assertEqual(len(accepted),1)
        self.assertEqual(sum(status=='rejected' for status,_ in results),3)
        self.assertEqual(self.snapshot(),dict(credits=15,total=15,available=5,locked=10,reserved=10))
        self.assertEqual(self.db.execute('SELECT count(*) FROM consultation_admissions').fetchone()[0],1)
        finish_request(self.db,accepted[0]['request_id'],success=False)
        self.assertEqual(self.snapshot()['available'],15)

    def test_admission_sequence_and_concurrent_jobs(self):
        grant(self.db,self.account,10,'test','m2c',uuid4().hex)
        a=self.submit(uuid4().hex)[1]
        b=self.submit(uuid4().hex)[1]
        self.assertLess(a['admission_seq'],b['admission_seq'])
        self.assertEqual(self.snapshot()['locked'],20)
        self.assertEqual(self.snapshot()['credits'],25)
        # Jobs may complete out of order without shifting the authorization sequence.
        finish_request(self.db,b['request_id'],success=True,
                       result_json={'lines':[6,7,8,9,7,8]}, provenance_json={'provider':'test'})
        self.assertEqual(self.snapshot()['credits'],15)
        self.assertEqual(self.snapshot()['available'],5)
        finish_request(self.db,a['request_id'],success=False)
        self.assertEqual(self.snapshot()['credits'],15)
        self.assertEqual(self.snapshot()['available'],15)
        self.assertEqual(self.snapshot()['locked'],0)

    def test_idempotent_retries_do_not_take_additional_ticket(self):
        key=uuid4().hex
        a=self.submit(key)[1]
        b=self.submit(key)[1]
        self.assertEqual(a['request_id'],b['request_id'])
        self.assertEqual(a['admission_seq'],b['admission_seq'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM consultation_admissions').fetchone()[0],1)

    def test_incomplete_reading_cannot_settle_or_debit(self):
        from gnosis_platform.transactions import TransactionError
        r=self.submit(uuid4().hex)[1]
        with self.assertRaises(TransactionError):
            finish_request(self.db,r['request_id'],success=True,
                           result_json={'lines':[6,7]},provenance_json={'provider':'test'})
        self.assertEqual(self.snapshot()['credits'],15)
        self.assertEqual(self.snapshot()['locked'],10)
        self.assertEqual(self.db.execute('SELECT status FROM service_requests WHERE request_id=?',
                         (r['request_id'],)).fetchone()[0], 'pending')
        finish_request(self.db,r['request_id'],success=False)
        self.assertEqual(self.snapshot()['available'],15)

    def test_failed_validation_does_not_grab_ticket(self):
        first=self.submit(uuid4().hex)[1]
        self.submit(uuid4().hex)
        self.assertEqual(self.db.execute('SELECT count(*) FROM consultation_admissions').fetchone()[0],1)
        self.assertEqual(self.snapshot()['credits'],15)
        finish_request(self.db,first['request_id'],success=False)


if __name__=='__main__':unittest.main()
