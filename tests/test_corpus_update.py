import json
import tempfile
import unittest
from pathlib import Path
from app.services import corpus as c
from scripts.update_corpus import inspect_release, install


class CorpusUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'export'
        self.source.mkdir()
        self.target = self.root / 'target'
        self.target.mkdir()
        for name in ('interpretations.json', 'interpretation_manifest.json'):
            (self.target / name).write_bytes((c.DATA / name).read_bytes())

    def export(self, data, manifest, *, changed=False):
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode() if changed else (c.DATA/'interpretations.json').read_bytes()
        cat = c.serialize_catalog(data['hexagrams'])
        manifest['files']['site/interpretations.json'] = c.sha(raw)
        manifest['files']['site/hexagrams_catalog.json'] = c.sha(cat)
        for key in ('corpus_version','schema_version','status','records_total','human_approved_records'):
            manifest['metadata'][key] = data[key]
        (self.source/'interpretations.json').write_bytes(raw)
        (self.source/'hexagrams_catalog.json').write_bytes(cat)
        (self.source/'release_manifest.json').write_bytes(json.dumps(manifest).encode() if changed else (c.DATA/'interpretation_manifest.json').read_bytes())

    def test_identical_and_corrupt(self):
        self.export(c.load(c.DATA/'interpretations.json'), c.load(c.DATA/'interpretation_manifest.json'))
        args = inspect_release(self.source)
        self.assertEqual(install(*args,target=self.target,backup_root=self.root/'backup')['status'],'unchanged')
        with (self.source/'hexagrams_catalog.json').open('ab') as f: f.write(b' ')
        with self.assertRaisesRegex(ValueError,'Catalog file hash mismatch'): inspect_release(self.source)

    def test_new_version_and_backup(self):
        data=c.load(c.DATA/'interpretations.json'); manifest=c.load(c.DATA/'interpretation_manifest.json')
        major,minor,patch=map(int,data['corpus_version'].split('.')); data['corpus_version']=f'{major}.{minor}.{patch+1}'
        for r in data['hexagrams']:r['corpus_version']=data['corpus_version']
        self.export(data,manifest,changed=True)
        args=inspect_release(self.source)
        old=(self.target/'interpretations.json').read_bytes()
        self.assertEqual(install(*args,target=self.target,backup_root=self.root/'backup')['status'],'validated')
        self.assertEqual((self.target/'interpretations.json').read_bytes(),old)
        result=install(*args,target=self.target,backup_root=self.root/'backup',apply=True)
        self.assertEqual(result['status'],'installed')
        self.assertEqual((Path(result['backup'])/'interpretations.json').read_bytes(),old)
        self.assertEqual((self.target/'interpretations.json').read_bytes(),args[1])
        self.assertEqual(install(*args,target=self.target,backup_root=self.root/'backup',apply=True)['status'],'unchanged')
        with self.assertRaisesRegex(ValueError,'higher corpus version'):
            install(c.load(c.DATA/'interpretations.json'),old,(c.DATA/'interpretation_manifest.json').read_bytes(),target=self.target,backup_root=self.root/'backup',apply=True)

    def test_invalid_identity_even_with_correct_file_hashes(self):
        data=c.load(c.DATA/'interpretations.json'); manifest=c.load(c.DATA/'interpretation_manifest.json')
        data['hexagrams'][0]['bits']='000000'
        self.export(data,manifest,changed=True)
        with self.assertRaisesRegex(ValueError,'Identity mismatch'): inspect_release(self.source)
