import tempfile
import unittest
from pathlib import Path
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect, migrate
from gnosis_platform.registry import SERVICES

class FoundationTests(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(SERVICES['iching.qrng_private'].provider,'qci')
        self.assertEqual(SERVICES['iching.qrng_private'].fallback,'anu')
        self.assertEqual(SERVICES['iching.quantum_future'].credits,10)
        self.assertEqual(SERVICES['iching.classic'].cooldown_seconds,0)
    def test_migrations_idempotent_and_fk(self):
        with tempfile.TemporaryDirectory() as temp:
            with connect(Path(temp)/'test.sqlite3') as db:
                self.assertEqual(
            migrate(db),
            sorted(
                p.name
                for p in (
                    Path(__file__).resolve().parents[1]
                    / 'gnosis_platform'
                    / 'migrations'
                ).glob('*.sql')
            )
        )
                self.assertEqual(migrate(db),[])
                names={row[0] for row in db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
                self.assertTrue({'accounts','credit_ledger','consultations','notification_outbox','payment_events'} <= names)
                self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
                with self.assertRaises(Exception):
                    db.execute("INSERT INTO account_keys(key_id, account_id, algorithm, public_key_b64url) VALUES ('k','nonexistent','Ed25519','xxx')")
if __name__ == '__main__': unittest.main()
