import unittest
from app.services.readings import reading_at,sample_data,interpretation_by_number

class ReadingTests(unittest.TestCase):
    def test_all_128(self):
        data=sample_data()
        self.assertEqual(len(data['readings']),128)
        self.assertEqual(len(interpretation_by_number()),64)
        for i in range(128):
            row=reading_at(i)
            r=row['reading']
            self.assertEqual(len(r['lines']),6)
            self.assertEqual(len(r['line_values_bottom_to_top']),6)
            self.assertEqual(r['moving_positions_bottom_to_top'],
                             [j+1 for j,v in enumerate(r['line_values_bottom_to_top']) if v in (6,9)])
            self.assertEqual(r['moving_flag_matches'],sum(l['moving_flag_agrees'] for l in r['lines']))
            self.assertTrue(row['interpretations']['now'])
            self.assertTrue(row['interpretations']['becoming'])
            self.assertTrue(row['demo_only'])

if __name__=='__main__':unittest.main()
