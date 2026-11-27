#!/usr/bin/env python3
"""Explicit request-specific paid trial CLI; no automatic submissions."""
import argparse,json,sys
from pathlib import Path
from contextlib import closing, nullcontext
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.future_automation import request_lock
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect
from gnosis_platform.future_execution import submit,retrieve,record_billing,usage,runtime,job_row
from gnosis_platform.ibm_worker import settle_staged

def main():
    ap=argparse.ArgumentParser();s=ap.add_subparsers(dest='cmd',required=True);s.add_parser('status')
    for cmd in ('submit','retrieve','settle','usage','record-billing'):
        p=s.add_parser(cmd);p.add_argument('request_id')
        if cmd=='submit':p.add_argument('--remaining-seconds',type=float,required=True);p.add_argument('--authorize-paid-qpu-job',action='store_true')
        if cmd=='record-billing':
            p.add_argument('--seconds',type=float,required=True);p.add_argument('--apply',action='store_true',required=True);p.add_argument('--replace-expected',type=float);p.add_argument('--reason')
    a=ap.parse_args();spool=get_settings().data_dir/'ibm-results-restricted'
    lock=request_lock(get_settings().data_dir,a.request_id) if a.cmd!='status' else nullcontext()
    with lock, closing(connect()) as db:
        if a.cmd=='status':
            out=[]
            for row in db.execute('''SELECT j.request_id,r.service_id,j.status,r.status AS request_status,j.external_job_id,j.shots,j.metadata_json FROM ibm_future_jobs j JOIN service_requests r USING(request_id) ORDER BY j.created_at DESC'''):
                d=dict(row);m=json.loads(d.pop('metadata_json') or '{}');d['provider_usage']=m.get('provider_usage');d['operator_billing']=m.get('operator_billing');d['operator_billing_history']=m.get('operator_billing_history',[]);out.append(d)
        elif a.cmd=='submit':out=submit(db,a.request_id,authorized=a.authorize_paid_qpu_job,remaining=a.remaining_seconds)
        elif a.cmd=='retrieve':out=retrieve(db,a.request_id,spool)
        elif a.cmd=='settle':out=settle_staged(db,a.request_id,spool=spool)
        elif a.cmd=='usage':
            row=job_row(db,a.request_id);job=runtime().job(row['external_job_id']);assert job.job_id()==row['external_job_id'] and job.backend().name==row['backend'];out=usage(db,a.request_id,job)
        else:out=record_billing(db,a.request_id,a.seconds,replace_expected=a.replace_expected,reason=a.reason)
        print(json.dumps(out,indent=2))
if __name__=='__main__':main()
