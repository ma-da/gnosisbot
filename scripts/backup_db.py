#!/usr/bin/env python3
"""Consistent SQLite backup; refuses overwrite. Does NOT include protected filesystem archives/keys."""
import argparse, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out', type=Path, required=True);a=p.parse_args()
    src=get_settings().db_path.resolve(); dst=a.out.expanduser().resolve()
    repo=Path(__file__).resolve().parents[1]
    if not src.is_file() or dst==src or dst.is_relative_to(repo):p.error('Require existing source and destination outside repository')
    os.umask(0o077);dst.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(dst,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True) as source, sqlite3.connect(dst) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Backup integrity check failed')
        print('Consistent private backup:',dst)
    except BaseException:
        dst.unlink(missing_ok=True);raise
if __name__=='__main__':main()
