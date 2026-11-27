"""Run from the Gnosis repo root: python -m unittest discover -s tests -p 'test_workspace_feed.py' -v"""
import unittest
from datetime import datetime, timedelta, timezone
from gnosis_platform.account_workspace_feed import _normalize

NOW = datetime(2026, 11, 23, 20, 0, tzinfo=timezone.utc)

class WorkspaceFeedTests(unittest.TestCase):
    def test_recent_open_remote_and_sorted_by_value(self):
        date = (NOW - timedelta(days=2)).isoformat()
        entries = [
            {'id': 'job_low', 'title': 'Small job', 'createdAt': date, 'status': 'open', 'price': 20, 'priceType': 'fixed'},
            {'id': 'job_high', 'title': 'Big job', 'createdAt': date, 'status': 'open', 'price': 100, 'priceType': 'fixed'},
            {'id': 'job_closed', 'title': 'Closed', 'createdAt': date, 'status': 'closed', 'price': 800},
            {'id': 'job_old', 'title': 'Old', 'createdAt': (NOW-timedelta(days=30)).isoformat(), 'price': 500},
            {'id': 'job_local', 'title': 'Local', 'createdAt': date, 'isRemote': False, 'price': 600},
        ]
        got = _normalize({'bounties': entries}, now=NOW)
        self.assertEqual([r['id'] for r in got], ['job_high', 'job_low'])
        self.assertEqual(got[0]['reward_display'], '$100.00 fixed')

    def test_invalid_external_ids_rejected(self):
        entries = [{'id': '../evil', 'title': 'Bad', 'createdAt': NOW.isoformat(), 'price': 500},
                   {'id': 'valid_1', 'title': 'Good', 'createdAt': NOW.isoformat(), 'price': 25}]
        self.assertEqual([r['id'] for r in _normalize(entries, now=NOW)], ['valid_1'])

    def test_missing_or_unexpected_payload_fails_closed(self):
        self.assertEqual(_normalize({'unexpected': []}, now=NOW), [])
        self.assertEqual(_normalize('untrusted', now=NOW), [])

if __name__ == '__main__': unittest.main()
