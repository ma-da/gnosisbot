import unittest
from fastapi.testclient import TestClient
from app.main import app

class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)

    def test_single_stylesheet_is_served(self):
        response=self.client.get('/assets/css/global.css')
        self.assertEqual(response.status_code,200)
        self.assertIn('--ring-size',response.text)
        self.assertIn('--char-opacity',response.text)

    def test_reference_catalog(self):
        response=self.client.get('/api/v1/hexagrams')
        self.assertEqual(response.status_code,200)
        items=response.json()
        self.assertEqual(len(items),64)
        self.assertEqual(len(set(x['bits'] for x in items)),64)
        self.assertEqual(set(x['number'] for x in items),set(range(1,65)))

    def test_demo_catalog(self):
        response=self.client.get('/api/v1/demo/catalog')
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data['count'],128)
        self.assertEqual(len(data['readings']),128)
        for row in data['readings']:
            self.assertEqual(len(row['values']),6)
            self.assertTrue(0<=row['matches']<=6)
            self.assertEqual(row['moving_positions'],[i+1 for i,v in enumerate(row['values']) if v in (6,9)])

    def test_modes_honestly_report_capabilities(self):
        caps=self.client.get('/api/v1/capabilities').json()
        self.assertTrue(caps['standard']['enabled'])
        self.assertFalse(caps['quantum_entropy']['enabled'])
        self.assertFalse(caps['quantum_hardware']['fresh_qpu'])

    def test_featured_archived_reading(self):
        x=self.client.get('/api/v1/demo/readings/94').json()
        self.assertTrue(x['demo_only'])
        self.assertEqual(x['reading']['moving_flag_matches'],6)
        self.assertEqual(x['provenance']['job_id'],'dbqc109abdes73fo08b0')

if __name__=='__main__':
    unittest.main()
