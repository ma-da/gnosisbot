"""Offline regression suite using the supplied corpus plus the genuine cleaned demo."""
import importlib.util,json,copy,itertools,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse, Response
ROOT=Path(__file__).resolve().parents[1]; P=ROOT/'app/data'
from app.services import corpus as c
rows=c.load(P/'interpretations.json')['hexagrams']; data=c.load(P/'interpretations.json'); demo=c.load(P/'ibm_demo_128.json'); migration=c.load(P/'demo_migration_report.json')

def reading(vals):
    return {'lines':list(vals),'coin_bits_bottom_to_top':['1'*(v-6)+'0'*(9-v) for v in vals], 'now_yang_bits_bottom_to_top':[v%2 for v in vals], 'becoming_yang_bits_bottom_to_top':[v%2 ^ int(v in (6,9)) for v in vals], 'moving_positions_bottom_to_top':[i+1 for i,v in enumerate(vals) if v in (6,9)]}

class CorpusTests(unittest.TestCase):
    def test_manifest_exact(self):
        m=c.load(P/'interpretation_manifest.json')
        self.assertEqual(c.sha((P/'interpretations.json').read_bytes()),m['files']['site/interpretations.json'])
        self.assertEqual(c.sha(c.serialize_catalog(rows)),m['files']['site/hexagrams_catalog.json'])
        self.assertEqual(c.validate_corpus(data,rows),rows)
    def test_catalog_bytes(self):
        with patch.object(c,'DATA',P):
            c.corpus.cache_clear();c.catalog_bytes.cache_clear();self.assertEqual(c.catalog_bytes(),c.serialize_catalog(c.load(P/'interpretations.json')['hexagrams']))
    def test_demo_projection(self):
        self.assertEqual(c.sha((P/'ibm_demo_128.json').read_bytes()),migration['clean_archive_sha256']);self.assertEqual(c.digest(c.physical_projection(demo)),migration['physical_projection_sha256_before'])
        for r in demo['readings']:
            new,refs=c.project_reading(r,rows);self.assertEqual(new,r);self.assertEqual(refs['now']['bits'],r['now_bits_bottom_to_top'])
    def test_all_casts(self):
        for v in itertools.product(range(6,10),repeat=6):
            r=reading(v);p,refs=c.project_reading(r,rows);self.assertEqual(p,r);self.assertEqual(refs['now']['bits'],''.join(map(str,r['now_yang_bits_bottom_to_top'])))
    def test_legacy_and_raw(self):
        r=copy.deepcopy(demo['readings'][0]);r['now'].update(poem_title='old',reflection_question='old',richter_heading='old');prov={'source_attribution':{'source_link':'https://i-chingguru.vercel.app/'},'selection':{'shots':[{'coin_bits':'1'*18,'moves':'101010','values':[9]*6}],'selected_shot_index':0},'external_job_id':'xyz','circuit_sha256':'abc'}
        before=copy.deepcopy((r,prov));out=c.project_payload({'reading':r,'provenance':prov},rows)
        self.assertEqual((r,prov),before); self.assertEqual(out['reading'],demo['readings'][0]); self.assertEqual(out['provenance']['selection'],prov['selection']);self.assertNotIn('source_attribution',out['provenance']);self.assertEqual(out['literary_provenance']['corpus_version'],data['corpus_version'])
    def test_mismatch(self):
        r=reading([6]*6);r['now']={'king_wen_number':1};self.assertRaises(ValueError,c.project_reading,r,rows)
        r=reading([6]*6);r['moving_positions_bottom_to_top']=[];self.assertRaises(ValueError,c.project_reading,r,rows)
    def test_rune_untouched(self):
        r={'receipt':{'service_id':'runes.sticks.classic'},'result':{'reading':{'payload':{'sources':['x']}},'provenance':{'source_attribution':'old'}}};self.assertIs(c.project_payload(r,rows),r)

class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);path=Path(self.temp.name)
        (path/'interpretations.json').write_bytes((P/'interpretations.json').read_bytes());(path/'robots.txt').write_text('Sitemap: https://gnosis.bot/sitemap.xml\n');(path/'sitemap.xml').write_text('<urlset/>')
        self.patch=patch.object(c,'DATA',path);self.patch.start();self.addCleanup(self.patch.stop);c.corpus.cache_clear();c.catalog_bytes.cache_clear();self.addCleanup(c.corpus.cache_clear);self.addCleanup(c.catalog_bytes.cache_clear)
        a=FastAPI();a.add_middleware(c.CorpusPresentation)
        @a.get('/api/v1/hexagrams')
        def old():return [{'old':True}]
        @a.get('/api/v1/demo/catalog')
        def catalog():return {'readings':[{'index':0,'now':1,'becoming':2,'values':[6]*6,'matches':6,'moving_positions':[1,2,3,4,5,6]}],'source_attribution':{'name':'Richter'}}
        @a.get('/api/v1/demo/readings/{i}')
        def shot(i:int):return {'reading':demo['readings'][i],'provenance':{'backend':demo['backend'],'source_attribution':{'name':'Richter'}}}
        @a.post('/api/v1/consultations')
        def consult(service:str):return {'receipt':{'service_id':'iching.'+service},'result':{'reading':reading([6,7,8,9,7,8]),'provenance':{'provider':service,'source_attribution':{'name':'Richter'},'external_job_id':'test'}}}
        @a.get('/api/v1/consultations/{id}')
        def status(id:str):return {'service_id':'iching.quantum_future','result':{'reading':reading([9]*6),'provenance':{'selection':{'shots':[{'coin_bits':'1'*18}]}}}}
        @a.get('/api/v1/accounts/readings/{id}')
        def history(id:str):
            if id=='denied':raise HTTPException(401)
            return {'service_id':'iching.quantum_past','reading':reading([7]*6),'provenance':{'physical_coin_bits':'001'*6}}
        @a.get('/api/v1/accounts/readings/{id}/verification')
        def receipt(id:str):return Response(b'{"saved_bytes":{"reading_json":"old Richter"}}',media_type='application/json')
        @a.get('/quantum-oracle.html')
        @a.get('/rune-oracle.html')
        def page():return HTMLResponse('<html>same frontend</html>')
        self.client=TestClient(a)
    def test_live_catalog(self):self.assertEqual(self.client.get('/api/v1/hexagrams').content,c.serialize_catalog(c.load(P/'interpretations.json')['hexagrams']))
    def test_demo(self):
        self.assertNotIn('source_attribution',self.client.get('/api/v1/demo/catalog').json());res=self.client.get('/api/v1/demo/readings/1').json();self.assertEqual(res['reading'],demo['readings'][1]);self.assertIn('confucian',res['interpretations']['now'])
    def test_sources(self):
        for service in ['qrng_private','qrng_public','quantum_past']:
            res=self.client.post('/api/v1/consultations',params={'service':service});self.assertEqual(res.status_code,200);self.assertIn('taoist',res.json()['result']['interpretations']['now']);self.assertNotIn('source_attribution',res.json()['result']['provenance'])
        res=self.client.get('/api/v1/consultations/x').json();self.assertEqual(res['result']['provenance']['selection']['shots'][0]['coin_bits'],'1'*18)
        self.assertEqual(self.client.get('/api/v1/accounts/readings/x').json()['reading'],reading([7]*6))
    def test_receipt_unchanged(self):
        r=self.client.get('/api/v1/accounts/readings/x/verification');self.assertEqual(r.content,b'{"saved_bytes":{"reading_json":"old Richter"}}');self.assertIn('noindex',r.headers['x-robots-tag'])
    def test_robots_headers(self):
        for s in ['/quantum-oracle.html','/rune-oracle.html']:
            r=self.client.get(s);self.assertNotIn('x-robots-tag',r.headers); q=self.client.get(s+'?reading=');self.assertEqual(q.content,r.content);self.assertEqual(q.headers['x-robots-tag'],'noindex, nofollow');self.assertIn('no-store',q.headers['cache-control'])
        self.assertEqual(self.client.get('/api/v1/accounts/readings/denied').status_code,401);self.assertEqual(self.client.get('/sitemap.xml').status_code,200);self.assertIn('Sitemap:',self.client.get('/robots.txt').text)
