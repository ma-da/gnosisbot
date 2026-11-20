"""M3D aggregate privacy, source/date filters, mask counts, expected statistics."""
import tempfile
import unittest
from pathlib import Path
from gnosis_platform.db import connect,migrate
from gnosis_platform.research_dashboard import distribution_data,summary_data,timeseries_data,_gamma_q
from fastapi import HTTPException

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.temp.name)/'db.sqlite3')
        migrate(self.db)
        # Research projections need complete relational rows; seed minimum required records.
        self.db.execute("INSERT INTO accounts(account_id,created_at) VALUES (?,?)",('acct','2026-11-01T00:00:00Z'))
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def add(self,cid,day,mask,moving=0,source='qci'):
        # Insert direct projection with foreign-key parent placeholders; use schema introspection
        # to construct valid consultation/measurement rows from actual project layout.
        self.db.execute('''INSERT INTO consultations (consultation_id,account_id,application_id,status,question,inquiry_style,created_at)
             VALUES(?,?,?,?,?,?,?)''',(cid,'acct','iching','completed','private sensitive text','general',day+'T12:00:00Z'))
        self.db.execute('''INSERT INTO reading_measurements(measurement_id,consultation_id,source_id,measurement_status,provider_metadata_json,recorded_at)
             VALUES(?,?,?,?,?,?)''',('m'+cid,cid,source,'metadata_only','{}',day+'T12:00:00Z'))
        self.db.execute('''INSERT INTO reading_facts(consultation_id,account_id,research_subject_id,application_id,source_id,
        primary_mask,relating_mask,moving_mask,moving_count,line_values_json,completed_at,measurement_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(cid,'acct','private-research-id','iching',source,mask,mask^moving,moving,moving.bit_count(), '[7,7,7,7,7,7]',day+'T12:00:00Z','m'+cid))
    def test_empty_baseline(self):
        d=distribution_data(self.db);self.assertEqual(len(d['hexagrams']),64)
        self.assertEqual(d['total_readings'],0);self.assertIsNone(d['goodness_of_fit']['p_value'])
        self.assertEqual(summary_data(self.db)['moving_rate'],None)
    def test_count_and_privacy(self):
        self.add('a'*32,'2026-11-02',5,3)
        self.add('b'*32,'2026-11-03',5,0)
        self.add('c'*32,'2026-11-03',22,0,'ibm_marrakesh')
        d=distribution_data(self.db);self.assertEqual(d['total_readings'],3)
        self.assertEqual(d['hexagrams'][5]['count'],2)
        self.assertEqual(d['hexagrams'][22]['count'],1)
        self.assertEqual(d['hexagrams'][5]['expected'],3/64)
        self.assertNotIn('private sensitive',str(d))
        self.assertNotIn('acct',str(d))
        self.assertEqual(distribution_data(self.db,source='qci')['total_readings'],2)
        self.assertEqual(distribution_data(self.db,start='2026-11-03',end='2026-11-04')['total_readings'],2)
        self.assertEqual(distribution_data(self.db,moving='yes')['total_readings'],1)
        self.assertEqual(distribution_data(self.db,phase='relating')['hexagrams'][6]['count'],1)
        t=timeseries_data(self.db,mask=5)
        self.assertEqual([p['observed'] for p in t['points']],[1,1])
        self.assertEqual(summary_data(self.db)['moving_line_total'],2)
    def test_stats_and_validation(self):
        self.assertAlmostEqual(_gamma_q(1,1),0.367879441,places=7)
        self.assertAlmostEqual(_gamma_q(2,1),0.735758882,places=7)
        with self.assertRaises(HTTPException):distribution_data(self.db,phase='bogus')
        with self.assertRaises(HTTPException):distribution_data(self.db,start='2026-11-10',end='2026-11-02')
        with self.assertRaises(HTTPException):distribution_data(self.db,source='x;DROP TABLE')
if __name__=='__main__':unittest.main()
