#!/usr/bin/env python3
"""Explicit, local contact migration and cleanup; never sends mail."""
import argparse, os, sqlite3, sys
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect, migrate
from gnosis_platform.contact_protection import prune, statistics, policy

if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['migrate','prune','status']); parser.add_argument('--apply',action='store_true'); args=parser.parse_args()
    if args.command!='status' and not args.apply: parser.error('--apply required')
    s=get_settings()
    if not s.db_path.is_file(): raise SystemExit('Database missing')
    with closing(connect()) as db:
        if args.command=='migrate':
            expected={p.name for p in (Path(__file__).resolve().parents[1]/'gnosis_platform/migrations').glob('*.sql')}
            actual={r[0] for r in db.execute('SELECT version FROM schema_migrations')}
            pending=expected-actual
            if not actual<=expected or not pending<={'9018_contact_hardening.sql'}:raise SystemExit('Unexpected migration set; stop')
            if pending:
                d=s.data_dir/'certificates-private'
                if not d.is_dir() or d.is_symlink() or d.stat().st_mode&0o077:raise SystemExit('Unsafe backup directory')
                target=d/('pre9018-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite3')
                fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
                with closing(sqlite3.connect(target)) as backup:
                    db.backup(backup)
                    if backup.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise SystemExit('Backup verification failed')
                print('Database backup:',target,flush=True)
            print('Applied:',migrate(db))
        elif args.command=='prune':
            db.execute('BEGIN IMMEDIATE')
            try:n=prune(db);db.commit()
            except Exception:db.rollback();raise
            print('Expired quarantined messages erased from active rows:',n)
        else:
            print('Policy (minimum seconds, TTL seconds, email/day, global/hour, quarantine days):',policy())
            print('Last 24 hours:',statistics(db))
