#!/usr/bin/env python3
"""Explicit arm/disarm/status and guarded migration; no hardware submissions here."""
import argparse,json,os,sys,sqlite3
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.db import connect,migrate
from gnosis_platform.config import get_settings
from gnosis_platform.future_auto_policy import arm,disarm,enabled,production_enabled

def main():
    os.umask(0o077);a=argparse.ArgumentParser();sub=a.add_subparsers(dest='cmd',required=True)
    sub.add_parser('status');p=sub.add_parser('arm');p.add_argument('--jobs',type=int,required=True);p.add_argument('--remaining-seconds',type=float,required=True);p.add_argument('--reserve-floor',type=float,default=250);p.add_argument('--authorize-paid-hardware',action='store_true',required=True)
    for cmd in ('disarm','migrate'):
        p=sub.add_parser(cmd);p.add_argument('--apply',action='store_true',required=True)
    p=sub.add_parser('cancel-queued');p.add_argument('request_id');p.add_argument('--apply',action='store_true',required=True)
    args=a.parse_args();s=get_settings()
    if not s.db_path.is_file():raise SystemExit('Database missing')
    with closing(connect()) as db:
        if args.cmd=='arm':out=arm(db,args.jobs,args.remaining_seconds,args.reserve_floor)
        elif args.cmd=='disarm':disarm(db);out={'disarmed':True}
        elif args.cmd=='cancel-queued':
            from gnosis_platform.future_automation import request_lock
            from gnosis_platform.future_execution import job_row
            from gnosis_platform.transactions import finish_request
            from gnosis_platform.ibm_future_queue import stamp
            rid=args.request_id
            with request_lock(s.data_dir,rid):
                row=job_row(db,rid)
                if row['status']!='queued' or row['external_job_id'] or row['submit_claimed_at'] or row['request_status'] not in ('pending','failed'):
                    raise ValueError('Only never-claimed queued requests can be cancelled')
                finish_request(db,rid,success=False)
                db.execute("UPDATE ibm_future_jobs SET status='failed',failure_code='operator_cancelled_unsubmitted',finished_at=?,updated_at=? WHERE request_id=? AND status='queued'",(stamp(),stamp(),rid))
                out={'request_id':rid,'status':'failed','credits_refunded':10}
        elif args.cmd=='migrate':
            actual={x[0] for x in db.execute('SELECT version FROM schema_migrations')};expected={x.name for x in (Path(__file__).resolve().parents[1]/'gnosis_platform/migrations').glob('*.sql')};pending=expected-actual
            if not actual<=expected or not pending<={'9017_future_production.sql'}:raise SystemExit('Unexpected migration set')
            if pending:
                d=s.data_dir/'certificates-private'
                if not d.is_dir() or d.is_symlink() or d.stat().st_mode&0o077:raise SystemExit('Unsafe backup directory')
                dest=d/('pre9017-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite3');fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
                with closing(sqlite3.connect(dest)) as other:
                    db.backup(other)
                    if other.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise SystemExit('Backup verification failed')
                print('Backup:',dest,flush=True)
            out=migrate(db)
        else:
            out={'enabled':enabled(),'production_enabled':production_enabled(),'permits':[dict(r) for r in db.execute('SELECT * FROM future_auto_permits ORDER BY created_at DESC')], 'requests':[dict(r) for r in db.execute('SELECT a.*,j.status,j.external_job_id,r.service_id,r.status AS request_status FROM future_auto_requests a JOIN ibm_future_jobs j USING(request_id) JOIN service_requests r USING(request_id) ORDER BY j.created_at')]}
        print(json.dumps(out,indent=2))
if __name__=='__main__':main()
