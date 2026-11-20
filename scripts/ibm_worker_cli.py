#!/usr/bin/env python3
"""Operator-only IBM worker CLI; no public routes, no background process."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect, migrate
from gnosis_platform.ibm_worker import submit_one, retrieve_one, settle_staged, capacity_scenarios
from gnosis_platform.ibm_future_queue import list_needing_reconciliation


def main():
    ap=argparse.ArgumentParser(description='Gnosis IBM Future worker operator controls')
    ap.add_argument('--spool', default=str(get_settings().data_dir/'ibm-results-restricted'))
    sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    sub.add_parser('capacity')
    submit=sub.add_parser('submit')
    submit.add_argument('--backend',choices=['ibm_marrakesh','ibm_fez'],required=True)
    submit.add_argument('--authorize-paid-qpu-job',action='store_true')
    retrieve=sub.add_parser('retrieve');retrieve.add_argument('request_id')
    settle=sub.add_parser('settle');settle.add_argument('request_id')
    args=ap.parse_args()
    if args.command=='capacity':
        print(json.dumps(capacity_scenarios(),indent=2));return
    with connect() as db:
        migrate(db)
        if args.command=='status':
            rows=list_needing_reconciliation(db)
            print(json.dumps([{k:r.get(k) for k in ('request_id','status','backend','external_job_id','shots','updated_at')} for r in rows],indent=2));return
        if args.command=='submit':
            result=submit_one(db,backend_name=args.backend, enable_live=args.authorize_paid_qpu_job)
        elif args.command=='retrieve':
            result=retrieve_one(db,args.request_id,spool=args.spool)
        else:
            result=settle_staged(db,args.request_id,spool=args.spool)
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
