import unittest
from quantum.iching.circuit import now_and_becoming
from quantum.iching.verification import check_classical_line_truth_table, check_readout_vectors

class TestCircuit(unittest.TestCase):
    def test_truth_table(self):
        self.assertTrue(check_classical_line_truth_table())

    def test_eight_line_values(self):
        for n in range(8):
            bits = format(n, '03b')
            r = now_and_becoming(bits * 6)
            self.assertEqual(r['line_values_bottom_to_top'], [6 + bits.count('1')] * 6)
            self.assertEqual(r['moving_positions_bottom_to_top'], list(range(1, 7)) if bits.count('1') in (0,3) else [])

    def test_full_six_line_vector(self):
        self.assertTrue(check_readout_vectors())

    def test_mismatch_preserved(self):
        r = now_and_becoming('000' * 6, '000000')
        self.assertEqual(r['moving_flag_matches'], 0)
        self.assertTrue(all(x['moving_classically_verified'] for x in r['lines']))
        self.assertTrue(all(x['moving_flag_agrees'] is False for x in r['lines']))

if __name__ == '__main__': unittest.main()
