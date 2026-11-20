import json, unittest
from copy import deepcopy
from quantum.sticks.recognition import analyze_casting, public_timeline, PROFILE_SHA256
from quantum.sticks.recognition import engine as e
class RecognitionTests(unittest.TestCase):
    def test_profile(self):
        self.assertEqual(PROFILE_SHA256,'dfa681432bcb00a68f390660f1244d90baabb42b2f87648762b360c8923beb1e')
        self.assertEqual(len(e.APPROVED_QUALITY),24)
    def test_replay(self):
        for seed in range(5000,5005):
            c=e.synthetic_casting(seed); original=deepcopy(c); t=analyze_casting(c)
            self.assertEqual(c,original)
            for step in (12,24,36,48,60,72):
                prefix={'chords':c['chords'][:step]}; rows=e.detect_calibration(prefix)
                self.assertEqual(e.reading_snapshot(prefix,rows,step,e.measure_candidates(prefix,rows)),t['frames'][step],(seed,step))
            for x in t['final']['shown'].values():
                self.assertEqual(x['occurrence_count'],len(x['occurrence_ids']))
                self.assertIn(x['primary_id'],x['occurrence_ids']); self.assertGreaterEqual(x['size'],e.BOLD_MIN_SIZE); self.assertGreaterEqual(x['quality'],e.APPROVED_QUALITY[x['rune']])
            pub=public_timeline(t); self.assertEqual(pub['final'],pub['frames']['72']); json.dumps(pub,allow_nan=False)
            for f in pub['frames'].values():
                for x in f['shown'].values(): self.assertTrue(set(x['occurrence_ids'])<=pub['candidates'].keys())
                for x in f['compounds']: self.assertTrue(set(x['candidate_ids'])<=pub['candidates'].keys())
            for evt in pub['events']:
                for k in ('primary_id','previous_primary_id'):
                    if evt.get(k): self.assertIn(evt[k],pub['candidates'])
                self.assertTrue(set(evt.get('parent_ids',[]))<=pub['candidates'].keys())
    def test_empty_and_duplicates(self):
        c=e.from_pairs([(0,0),(0,128),(128,0),(0,128)])
        self.assertEqual(len(analyze_casting(c)['casting']['chords']),4)
        self.assertEqual(analyze_casting({'chords':[]})['final']['shown'],{})
    def test_original_template_atlas(self):
        for rule in e.GRAMMAR["runes"]:
            c=e.template_fixture(e.GRAMMAR,rule["name"])
            rows=e.detect_v07(c)
            self.assertTrue(any(x["rune"]==rule["name"] and len(e.support_key(x))==rule["support_count"] for x in rows),rule["name"])
    def test_invalid(self):
        for c in ({'chords':[{'sequence':2,'endpoint_a':0,'endpoint_b':1}]},{'chords':[{'sequence':1,'endpoint_a':256,'endpoint_b':0}]},{'chords':[],'slots':72}):
            with self.assertRaises(ValueError): analyze_casting(c)
if __name__=='__main__': unittest.main()
