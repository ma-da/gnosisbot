import unittest
import tempfile
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gnosis_platform.db import connect,migrate
from gnosis_platform.identity import b64e,register,challenge,verify,session_account,create_invitation,grant,revoke

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.dir.name)/'test.db')
        migrate(self.db)
        self.private=Ed25519PrivateKey.generate()
        self.public=b64e(self.private.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw))

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_register_invitation_and_login(self):
        token=create_invitation(self.db,'media',25)
        user=register(self.db,self.public,token)
        self.assertEqual(user['credits'],25)
        with self.assertRaises(ValueError): register(self.db,self.public,token)
        row=self.db.execute('SELECT * FROM credit_accounts').fetchone()
        self.assertEqual(row['available'],25)
        self.assertEqual(self.db.execute('SELECT count(*) FROM credit_ledger').fetchone()[0],1)
        issued=challenge(self.db,user['account_id'])
        signature=b64e(self.private.sign(issued['message'].encode()))
        verified=verify(self.db,user['account_id'],issued['challenge_id'],issued['message'],signature)
        self.assertEqual(session_account(self.db,verified['session_token'])['account_id'],user['account_id'])
        with self.assertRaises(ValueError): verify(self.db,user['account_id'],issued['challenge_id'],issued['message'],signature)
        revoke(self.db,verified['session_token'])
        self.assertIsNone(session_account(self.db,verified['session_token']))

    def test_wrong_signature_does_not_consume_challenge(self):
        user=register(self.db,self.public)
        issued=challenge(self.db,user['account_id'])
        other=Ed25519PrivateKey.generate()
        with self.assertRaises(ValueError):
            verify(self.db,user['account_id'],issued['challenge_id'],issued['message'],b64e(other.sign(issued['message'].encode())))
        good=b64e(self.private.sign(issued['message'].encode()))
        verify(self.db,user['account_id'],issued['challenge_id'],issued['message'],good)

    def test_grant_idempotency(self):
        user=register(self.db,self.public)
        self.assertTrue(grant(self.db,user['account_id'],10,'local_admin','test','grant:a'))
        self.assertFalse(grant(self.db,user['account_id'],10,'local_admin','test','grant:a'))
        self.assertEqual(self.db.execute('SELECT available FROM credit_accounts').fetchone()[0],10)
        with self.assertRaises(ValueError):grant(self.db,user['account_id'],11,'local_admin','test','grant:a')

if __name__=='__main__':unittest.main()
