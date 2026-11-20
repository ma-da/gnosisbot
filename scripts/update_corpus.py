#!/usr/bin/env python3
"""Validate a schema-2 I Ching site export and explicitly install it; no DB access."""
from pathlib import Path
import argparse, json, os, sys, tempfile, shutil
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import corpus as c
from gnosis_platform.config import get_settings


def inspect_release(source):
    source = Path(source)
    site = source / 'site' if (source / 'site').is_dir() else source
    manifest_path = source / 'release_manifest.json'
    if not manifest_path.is_file():
        manifest_path = site / 'release_manifest.json'
    manifest = manifest_path.read_bytes()
    m = json.loads(manifest)
    raw = (site / 'interpretations.json').read_bytes()
    cat = (site / 'hexagrams_catalog.json').read_bytes()
    data = json.loads(raw)
    c.require(c.sha(raw) == m['files']['site/interpretations.json'], 'Corpus file hash mismatch')
    c.require(c.sha(cat) == m['files']['site/hexagrams_catalog.json'], 'Catalog file hash mismatch')
    rows = c.validate_corpus(data, json.loads(cat))
    c.require(c.serialize_catalog(rows) == cat, 'Catalog serialization differs from API contract')
    for k in ('corpus_version', 'schema_version', 'status', 'records_total', 'human_approved_records'):
        c.require(m['metadata'][k] == data[k], 'Manifest metadata mismatch: ' + k)
    return data, raw, manifest


def atomic(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.corpus-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def install(data, raw, manifest, *, target, backup_root, apply=False):
    target = Path(target)
    files = {'interpretations.json': raw, 'interpretation_manifest.json': manifest}
    previous = {name: (target/name).read_bytes() for name in files}
    current = json.loads(previous['interpretations.json'])
    version = lambda x: tuple(map(int, x.split('.')))
    identical = previous == files
    c.require(identical or version(data['corpus_version']) > version(current['corpus_version']), 'Nonidentical updates require a higher corpus version')
    if not apply or identical:
        return {'status':'unchanged' if identical else 'validated', 'version': data['corpus_version']}
    backup = Path(backup_root).resolve() / ('corpus-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    c.require(not backup.is_relative_to(Path(__file__).resolve().parents[1]), 'Backup must be outside repository')
    backup.mkdir(parents=True, mode=0o700)
    for name, old in previous.items():
        p=backup/name; p.write_bytes(old); p.chmod(0o600)
    try:
        for name, content in files.items(): atomic(target/name, content)
    except BaseException:
        for name, content in previous.items(): atomic(target/name, content)
        raise
    return {'status':'installed', 'version':data['corpus_version'], 'backup':str(backup), 'restart_required':True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    g=p.add_mutually_exclusive_group(required=True); g.add_argument('--check',action='store_true'); g.add_argument('--apply', action='store_true')
    p.add_argument('--confirm-stopped',action='store_true')
    a=p.parse_args()
    if a.apply and not a.confirm_stopped:p.error('Stop API and worker; pass --confirm-stopped')
    data, raw, manifest=inspect_release(a.source)
    print(json.dumps(install(data,raw,manifest,target=c.DATA,backup_root=get_settings().data_dir/'corpus-backups',apply=a.apply),indent=2))
if __name__=='__main__': main()
