#!/usr/bin/env python3
"""Supervised worker. Default: retrieve/settle known jobs; no new paid submissions."""
from __future__ import annotations
import argparse,json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect,migrate
from gnosis_platform.event_worker import cycle
from gnosis_platform.completion_outbox import reconcile_completed


def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['once','watch','backfill-notification','status'])
    p.add_argument('request_id',nargs='?')
    p.add_argument('--backend',choices=['ibm_marrakesh','ibm_fez'],default='ibm_marrakesh')
    p.add_argument('--spool',default=str(get_settings().data_dir/'ibm-results-restricted'))
    p.add_argument('--interval',type=int,default=30)
    p.add_argument('--allow-paid-submission',action='store_true')
    p.add_argument('--admin-trial-recipient',action='store_true',
                   help='Explicitly allow operator test email for admin without verified contact')
    a=p.parse_args()
    if a.command=='watch' and not 10<=a.interval<=3600:p.error('--interval must be 10..3600 seconds')
    if a.allow_paid_submission and os.environ.get('GNOSIS_ENABLE_IBM_LIVE_SUBMISSION')!='YES':
        p.error('Paid submission requires GNOSIS_ENABLE_IBM_LIVE_SUBMISSION=YES')
    def iteration():
        with connect() as db:
            migrate(db)
            if a.command=='backfill-notification':
                if not a.request_id:p.error('backfill-notification requires REQUEST_ID')
                reconcile_completed(db,request_id=a.request_id)
                return {'backfilled_request_id':a.request_id,'status':'enqueued_without_sending'}
            if a.command=='status':
                job=db.execute("SELECT status,count(*) n FROM ibm_future_jobs GROUP BY status").fetchall()
                mail=db.execute("SELECT status,count(*) n FROM gnosis_completion_outbox GROUP BY status").fetchall()
                return {'ibm_jobs':{r['status']:r['n'] for r in job},
                        'notification_events':{r['status']:r['n'] for r in mail}}
            return cycle(db,spool=a.spool,backend=a.backend,
                         allow_submit=a.allow_paid_submission,
                         allow_admin_trial_email=a.admin_trial_recipient)
    if a.command!='watch':
        print(json.dumps(iteration(),indent=2));return
    # This is a separate recoverable process, not a background thread in Uvicorn.
    # SQLite events arrive on admission/settlement; polling only detects remote QPU completion.
    print('Event worker started; paid submission: '+str(a.allow_paid_submission),flush=True)
    while True:
        try:print(json.dumps(iteration(),separators=(',',':')),flush=True)
        except Exception as exc:
            print(json.dumps({'worker_error_type':type(exc).__name__}),file=sys.stderr,flush=True)
        time.sleep(a.interval)
if __name__=='__main__':main()
