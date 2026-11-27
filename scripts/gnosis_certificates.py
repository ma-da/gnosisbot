#!/usr/bin/env python3
"""Private certificate pilot CLI. No QPU, email, inventory or credit calls."""
import argparse,sys,json,sqlite3,os
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.db import connect,migrate
from gnosis_platform.certificate_store import ROW_SQL,issue,init_key,verify_record,need,ROOT
from gnosis_platform.certificate_render import check_fonts

def main():
    a=argparse.ArgumentParser();a.add_argument('command',choices=['migrate','init-key','preview','issue','status']);a.add_argument('--db',type=Path,required=True);a.add_argument('--data-dir',type=Path,required=True);a.add_argument('--service',default='iching.quantum_future');a.add_argument('--limit',type=int,default=1);a.add_argument('--apply',action='store_true');args=a.parse_args()
    if args.db.resolve()!=Path('/var/lib/gnosis/gnosis.sqlite3') or args.data_dir.resolve()!=Path('/var/lib/gnosis'):a.error('Explicit production paths required')
    if not args.db.is_file() or not 1<=args.limit<=100:a.error('Database missing or invalid limit')
    if args.command in ('migrate','init-key','issue') and not args.apply:a.error('Explicit --apply required')
    if args.command in ('migrate','preview','issue'):check_fonts()
    if args.command in ('preview','status'):
        db=sqlite3.connect(args.db.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
    else:db=connect(args.db)
    with closing(db):
        need(db.execute('SELECT count(*) FROM accounts').fetchone()[0]>0,'unexpected_empty_database')
        if args.command=='migrate':
            actual={r[0] for r in db.execute('SELECT version FROM schema_migrations')};expected={p.name for p in (ROOT/'gnosis_platform/migrations').glob('*.sql')};pending=expected-actual
            need(actual<=expected and pending<= {'9014_reading_completion_events.sql'},'unexpected_migrations')
            if not pending:print('Already migrated');return
            backup=args.data_dir/'certificates-private';backup.mkdir(mode=0o700,exist_ok=True);need(not backup.is_symlink() and backup.stat().st_mode&0o077==0,'unsafe_backup_directory')
            dest=backup/('pre9014-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite3')
            fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            with closing(sqlite3.connect(dest)) as target:db.backup(target);need(target.execute('PRAGMA quick_check').fetchone()[0]=='ok','backup_failed')
            print('Backup:',dest);print('Applied:',migrate(db));return
        if args.command=='init-key':print('Signing key:',init_key(db,args.data_dir));return
        if args.command=='status':
            print(json.dumps([{'service':r['service_id'],'certificate_id':r['certificate_id'],'signature_valid':verify_record(r,args.data_dir)} for r in db.execute('SELECT * FROM reading_certificates ORDER BY issued_at')],indent=2));return
        query=ROW_SQL;params=[]
        if args.service!='all':query+=' AND s.service_id=?';params.append(args.service)
        rows=db.execute(query+' ORDER BY c.finished_at,c.consultation_id LIMIT ?',(*params,args.limit)).fetchall()
        report=[]
        for row in rows:
            try:report.append(issue(db,row,args.data_dir,apply=args.command=='issue'))
            except Exception as e:report.append({'service':row['service_id'],'state':'blocked','reason':str(e) if type(e) is ValueError and str(e).isascii() and str(e).replace('_','').isalnum() else type(e).__name__})
        print(json.dumps(report,indent=2));return 1 if any(x['state']=='blocked' for x in report) else 0
if __name__=='__main__':sys.exit(main() or 0)
