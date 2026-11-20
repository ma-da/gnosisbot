from __future__ import annotations
import unittest
from datetime import datetime,timezone,timedelta
from gnosis_platform.nist_beacon import NISTError,parse_and_cast

NOW=datetime(2026,11,16,17,0,0,tzinfo=timezone.utc)
RID='0123456789abcdef0123456789abcdef'

def sample():
    return {'pulse':{
        'version':'2.0','statusCode':0,'chainIndex':2,'pulseIndex':2030455,
        'timeStamp':(NOW-timedelta(seconds=40)).isoformat().replace('+00:00','Z'),
        'outputValue':'A3'*64,'certificateId':'ab'*32,'signatureValue':'cd'*64,
    }}

class NISTBeaconTests(unittest.TestCase):
    def test_18_reproducible_bits_and_six_lines(self):
        a,provenance=parse_and_cast(sample(),RID,current_time=NOW)
        b,p2=parse_and_cast(sample(),RID,current_time=NOW)
        self.assertEqual(a,b)
        self.assertEqual(a['lines'],b['lines'])
        self.assertEqual(len(a['lines']),6)
        self.assertEqual(len(''.join(a['coin_bits_bottom_to_top'])),18)
        self.assertTrue(all(6<=x<=9 for x in a['lines']))
        self.assertEqual(provenance['provider'],'nist')
        self.assertFalse(provenance['signature_verified_locally'])
        self.assertFalse(provenance['independent_entropy_per_consultation'])
    def test_request_ids_personalize_same_pulse(self):
        a,_=parse_and_cast(sample(),RID,current_time=NOW)
        b,_=parse_and_cast(sample(),'f'*32,current_time=NOW)
        self.assertNotEqual(a['coin_bits_bottom_to_top'],b['coin_bits_bottom_to_top'])
    def test_stale_rejected(self):
        p=sample();p['pulse']['timeStamp']=(NOW-timedelta(minutes=12)).isoformat()
        with self.assertRaises(NISTError):parse_and_cast(p,RID,current_time=NOW)
    def test_invalid_pulse_rejected(self):
        p=sample();p['pulse']['statusCode']=1
        with self.assertRaises(NISTError):parse_and_cast(p,RID,current_time=NOW)
        p=sample();p['pulse']['outputValue']='0' * 16
        with self.assertRaises(NISTError):parse_and_cast(p,RID,current_time=NOW)
    def test_missing_signature_rejected(self):
        p=sample();p['pulse'].pop('signatureValue')
        with self.assertRaises(NISTError):parse_and_cast(p,RID,current_time=NOW)

if __name__=='__main__':unittest.main()
