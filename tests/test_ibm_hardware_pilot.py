import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('ibm_hardware_pilot',Path(__file__).resolve().parents[1]/'scripts'/'ibm_hardware_pilot.py')
pilot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
class PilotSummaryTests(unittest.TestCase):
    def test_summary(self):
        batch={'shots':[{'moving_flag_matches':6}]*127+[{'moving_flag_matches':5}],
               'selected_shot_index':3,'medoid_distance_sums':[120]*128}
        out=pilot.summary(batch)
        self.assertEqual(out['moving_flag_checks_agree'],767)
        self.assertEqual(out['all_six_flags_agree_shots'],127)
        self.assertEqual(out['medoid_score'],120)
if __name__=='__main__': unittest.main()
