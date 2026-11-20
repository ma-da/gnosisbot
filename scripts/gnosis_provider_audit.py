#!/usr/bin/env python3
"""Read-only readiness audit. Optional NIST HTTP probe; never submits QPU jobs."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.db import connect

def configured(k):return bool(os.environ.get(k))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--probe-nist',action='store_true')
    args=p.parse_args()
    flags={
        'accounts_api':os.environ.get('GNOSIS_ENABLE_ACCOUNTS_API')=='1',
        'qci':os.environ.get('GNOSIS_ENABLE_QCI')=='1' and configured('QCI_API_TOKEN'),
        'nist':os.environ.get('GNOSIS_ENABLE_NIST')=='1',
        'ibm_admin_trial':os.environ.get('GNOSIS_ENABLE_IBM_ADMIN_TRIAL')=='YES',
        'ibm_paid_submissions_armed':os.environ.get('GNOSIS_ENABLE_IBM_LIVE_SUBMISSION')=='YES',
        'ibm_auto_submissions_armed':os.environ.get('GNOSIS_ENABLE_IBM_AUTO_SUBMIT')=='YES',
        'resend_key':configured('RESEND_API_KEY'),
        'resend_sender':configured('GNOSIS_RESEND_FROM'),
        'account_email_verification':os.environ.get('GNOSIS_ENABLE_EMAIL_VERIFICATION')=='YES' and configured('GNOSIS_CONTACT_ENCRYPTION_KEY'),
    }
    info={'flags':flags,'notes':{
        'qci':'Catalog availability is configuration-derived; run one real QCI cast to confirm service health',
        'nist':'Public beacon v2, not private per-request quantum entropy',
        'ibm_future':'Admin trial route is distinct from general production service; new billable jobs need explicit operator authorization',
        'ibm_past':'Requires human-approved IBM inventory, plus an account-consultation delivery integration',
    }}
    try:
        with connect() as db:
            info['db']={'connected':True}
            checks={
                'approved_available_ibm_past':"SELECT COUNT(*) FROM ibm_inventory_items i JOIN ibm_inventory_batches b ON b.batch_id=i.batch_id WHERE b.status='approved' AND i.state='available'",
                'ibm_future_queued':"SELECT COUNT(*) FROM ibm_future_jobs WHERE status='queued'",
                'ibm_future_active':"SELECT COUNT(*) FROM ibm_future_jobs WHERE status IN ('submitting','submitted','running','result_ready')",
                'notifications_pending':"SELECT COUNT(*) FROM gnosis_completion_outbox WHERE status='pending'",
            }
            for k,q in checks.items():
                try:info['db'][k]=db.execute(q).fetchone()[0]
                except Exception as e:info['db'][k]='unavailable: '+type(e).__name__
    except Exception as e:
        info['db']={'connected':False,'error_type':type(e).__name__}
    if args.probe_nist:
        try:
            from gnosis_platform.nist_beacon import cast
            result,pv=cast('00000000000000000000000000000001')
            info['nist_probe']={'ok':True,'pulse_timestamp':pv['beacon_timestamp'],
                                 'pulse_index':pv['beacon_pulse'],'reading_lines':len(result['lines'])}
        except Exception as e:
            info['nist_probe']={'ok':False,'error_type':type(e).__name__,'message':str(e)}
    print(json.dumps(info,indent=2))

if __name__=='__main__':main()
