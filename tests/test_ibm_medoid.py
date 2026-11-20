"""Medoid and shot-decoding tests; no network or Qiskit dependency."""
import unittest
from quantum.iching.medoid import select_medoid, distance, canonical_payload
from quantum.iching.decoder import decode_register_arrays


def shot(coin, move=None):
    move=move or ''.join(str(int(coin[i:i+3].count('1') in (0,3))) for i in range(0,18,3))
    return {'coin_bits':coin,'moving_qpu_bits':move}


class IBMMedoidTests(unittest.TestCase):
    def test_global_medoid_not_quality_ranked(self):
        a=shot('010'*6)
        b=shot('111'*6)
        batch=[a]*100+[b]*28
        out=select_medoid(batch)
        self.assertEqual(out['selected']['coin_bits'],a['coin_bits'])
        self.assertEqual(out['scores'][out['selected_shot_index']],min(out['scores']))
        self.assertEqual(out['shots_count'],128)
        self.assertEqual(len(canonical_payload(out)['shots']),128)

    def test_invalid_batch_rejected(self):
        with self.assertRaises(ValueError):select_medoid([shot('010'*6)]*127)
        with self.assertRaises(ValueError):select_medoid([shot('010'*6)]*127+[shot('wrong')])

    def test_qpu_flags_not_substituted_for_coin_moving(self):
        incorrect=shot('000'*6,'000000')
        out=select_medoid([incorrect]*128)
        self.assertEqual(out['selected']['moving_positions_bottom_to_top'],[1,2,3,4,5,6])
        self.assertEqual(out['selected']['moving_flag_matches'],0)

    def test_binary_register_direction(self):
        shots=decode_register_arrays(['101'+'0'*15],['000001'],expected_shots=1)
        self.assertEqual(shots[0]['coin_bits'],'0'*15+'101')
        self.assertEqual(shots[0]['moving_qpu_bits'],'100000')

    def test_distance_matches_existing_js(self):
        a={'values':[6,7,8,9,7,8]};b={'values':[7,7,9,8,6,8]}
        # Differences: (6,7) 3; (8,9) 3; (9,8) 3; (7,6) 3
        self.assertEqual(distance(a,b),12)

if __name__=='__main__':unittest.main()
