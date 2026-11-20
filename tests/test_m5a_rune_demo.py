import json
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gnosis_platform.rune_oracle_adapter import (pouch_payload, sticks_payload,
    load_demo, PROFILE_SHA256, ROOT)
from gnosis_platform.rune_demo_api import router
from quantum.sticks.recognition import analyze_casting, public_timeline


class RuneDemoTests(unittest.TestCase):
    def test_pouch_rank_mapping(self):
        self.assertEqual([d['rune_id'] for d in pouch_payload([0,5,19])['payload']['draws']], [0,6,21])
        for ranks in ([24,0,0],[0,23,0],[0,0,22],[True,0,0]):
            with self.assertRaises(ValueError): pouch_payload(ranks)

    def test_sticks_complete_empty_casting(self):
        r = sticks_payload(['0'*64]*18)
        self.assertEqual(len(r['payload']['casting']['chords']),72)
        self.assertEqual(len(r['payload']['timeline']['frames']),73)
        self.assertEqual(r['payload']['timeline']['final']['shown'],{})
        self.assertNotIn('raw_bitstrings_msb_first',r['payload']['casting'])
        self.assertEqual(r['private_audit']['casting']['raw_bitstrings_msb_first'],['0'*64]*18)
        self.assertEqual(r['profile_sha256'],PROFILE_SHA256)
        json.dumps(r,allow_nan=False)

    def test_incomplete_or_legacy_rejected(self):
        for raw in (['0'*64]*17,['0'*128]*9,['x'*64]*18):
            with self.assertRaises(ValueError): sticks_payload(raw)

    def test_frozen_fixture_reproduction(self):
        for seed in (7,5000,5001):
            fixture = load_demo(f'sticks-{seed}')
            p = fixture['payload']
            self.assertEqual(p['timeline'],public_timeline(analyze_casting(p['casting'])))
            self.assertEqual(p['timeline']['final'],p['timeline']['frames']['72'])

    def test_no_public_private_archive(self):
        for id in ('pouch','sticks-7','sticks-5000','sticks-5001'):
            data = load_demo(id)
            self.assertEqual(data['source'],'synthetic_demo')
            self.assertNotIn('private_audit',data)
            self.assertNotIn('raw_bitstrings_msb_first',data['payload'].get('casting',{}))

    def test_route_gate_and_allowlist(self):
        app = FastAPI(); app.include_router(router)
        client = TestClient(app)
        with patch.dict(os.environ, {'GNOSIS_ENABLE_RUNE_DEMO':'0'}):
            self.assertEqual(client.get('/api/v1/runes/demo/catalog').status_code,404)
        with patch.dict(os.environ, {'GNOSIS_ENABLE_RUNE_DEMO':'1'}):
            self.assertEqual(len(client.get('/api/v1/runes/demo/catalog').json()['fixtures']),4)
            result=client.get('/api/v1/runes/demo/readings/pouch')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['source'],'synthetic_demo')
            self.assertEqual(client.get('/api/v1/runes/demo/readings/unknown').status_code,404)
            self.assertEqual(client.post('/api/v1/runes/demo/readings/pouch').status_code,405)

if __name__ == '__main__': unittest.main()
