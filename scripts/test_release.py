#!/usr/bin/env python3
"""Offline release gate. Run all tests in isolated environment, never production state."""
from pathlib import Path
import os, subprocess, sys, tempfile, shutil
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory(prefix='gnosis-test-') as tmp:
        # Inherit PATH only (plus platform-essential locale). No provider or user secrets.
        env={'PATH':os.environ['PATH'],'HOME':tmp,'PYTHONPATH':str(ROOT),'GNOSIS_DATA_DIR':str(Path(tmp)/'state'),'PYTHONUTF8':'1'}
        def run(*args):subprocess.run(args, cwd=ROOT, env=env, check=True)
        run(sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py','-v')
        if not shutil.which('node'):raise RuntimeError('Node 22+ required for frontend regression')
        for p in sorted((ROOT/'tests').glob('test_*.mjs')):run('node',str(p))
        for p in sorted((ROOT/'app/static/js').glob('*.js')):run('node','--check',str(p))
        run(sys.executable,'scripts/gnosis_db.py','init')
        run(sys.executable,'scripts/audit_corpus.py','--static')
        run(sys.executable,'scripts/verify_quantum.py','--hashes-only')
if __name__=='__main__':main()
