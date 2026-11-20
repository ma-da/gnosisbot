"""Run with python -m unittest discover -s tests -v; no provider access."""
import unittest
import random
from quantum.sticks.verification import check_decoder
from quantum.sticks.decoder import decode_batch
from quantum.sticks.hardware import select_screened, REFERENCE_HASH

class OfflineTests(unittest.TestCase):
    def test_decoder(self):
        self.assertTrue(check_decoder())

    def test_selection(self):
        rows=[dict(physical=i,abs_bias=i/10000,calibration_cost=.01) for i in range(156)]
        selected=select_screened({'wires':rows},exclude=(0,1))
        self.assertEqual([r['physical'] for r in selected],list(range(2,66)))
        with self.assertRaises(ValueError): select_screened({'wires':rows[:63]})
        self.assertEqual(len(REFERENCE_HASH),64)

    def test_diagnostics(self):
        from quantum.sticks.diagnostics import validate
        rng=random.Random(91)
        # TEST FIXTURE ONLY: synthetic data, never eligible for readings.
        for w in (64,128):
            shots=128*(1152//w)
            raw=[format(rng.getrandbits(w),f'0{w}b') for _ in range(shots)]
            def run(raw):
                result=dict(job_id='synthetic-test',manifest=dict(physical_qubits_by_classical_bit=list(range(w)),n_castings=128,shots=shots,backend='synthetic',sha256='synthetic'),castings=decode_batch(raw))
                return validate(result)
            report=run(raw)
            self.assertEqual(report['total_bits'],147456)
            self.assertEqual(len(report['pairs']),w*(w-1)//2)
            self.assertEqual(report['integrity'],'PASS')
            self.assertEqual(len(report['wires']),w)
            # Inject perfect correlation into bits c0 and c1, detectable after Holm.
            altered=[s[:-2]+s[-1]*2 for s in raw]
            report=run(altered)
            self.assertLess(report['pairs'][0]['p_holm'],.05)

if __name__=='__main__': unittest.main()
