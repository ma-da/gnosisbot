"""Crash-safe IBM result processing and completion email dispatch.

Runs as a separate process; never as an ephemeral HTTP request/background task.
Local SQLite is the durable event queue. Only known submitted IBM jobs are
retrieved; ambiguous 'submitting' claims always require human reconciliation.
"""
from __future__ import annotations
import os
import traceback
from pathlib import Path
from .ibm_worker import retrieve_one,settle_staged,submit_one
from .ibm_future_queue import queue_request
from .ibm_past_delivery import recover_pending
from .completion_outbox import dispatch_one,flag_stale_claims_for_review

ACTIVE=('submitted','running','result_ready')


def cycle(db, *, spool, backend='ibm_marrakesh', allow_submit=False,
          allow_admin_trial_email=False, max_jobs=10):
    report={'processed':[],'submitted':None,'mail':None,'needs_review':[],'requeued_admissions':[],
            'stale_email_claims_flagged':flag_stale_claims_for_review(db)}
    # Finish local IBM Past admissions interrupted before synchronous settlement.
    # This never accesses QPU hardware or submits paid jobs.
    try:
        report['ibm_past_recovered'] = recover_pending(db,limit=max_jobs)
    except Exception as exc:
        report['needs_review'].append({'source':'ibm_past', 'error_type':type(exc).__name__})
    # Repair a crash after credit reservation but before admin trial queue insertion.
    # Queueing is local and free; this never sends a hardware request.
    stranded=db.execute('''SELECT r.request_id FROM service_requests r
       WHERE r.service_id='iching.quantum_future' AND r.status='pending'
       AND NOT EXISTS (SELECT 1 FROM ibm_future_jobs j WHERE j.request_id=r.request_id)
       ORDER BY r.started_at,r.request_id LIMIT ?''',(max_jobs,)).fetchall()
    for item in stranded:
        try:
            queue_request(db,item['request_id'])
            report['requeued_admissions'].append(item['request_id'])
        except Exception as exc:
            report['needs_review'].append({'request_id':item['request_id'],
                                           'error_type':type(exc).__name__})
    jobs=db.execute('''SELECT j.request_id,j.status,r.status AS request_status
      FROM ibm_future_jobs j JOIN service_requests r ON r.request_id=j.request_id
      WHERE j.status IN ('submitted','running','result_ready')
      ORDER BY j.created_at,j.request_id LIMIT ?''',(max_jobs,)).fetchall()
    for j in jobs:
        rid=j['request_id']
        try:
            if j['request_status']=='completed':
                # Resume after crash between financial settlement and IBM status update.
                result=settle_staged(db,rid,spool=spool)
            else:
                result = ({'status':'result_ready'} if j['status']=='result_ready'
                          else retrieve_one(db,rid,spool=spool))
                if isinstance(result,dict) and ('spool_path' in result or result.get('status')=='result_ready'):
                    result=settle_staged(db,rid,spool=spool)
            if result.get('status')=='needs_operator_reconciliation':
                report['needs_review'].append({'request_id':rid,'reason':'ibm_terminal_status',
                                               'ibm_status':result.get('ibm_status')})
            report['processed'].append({'request_id':rid,'result':result})
        except Exception as exc:
            # A transient network failure is NOT proof of QPU job failure.
            report['needs_review'].append({'request_id':rid,'error_type':type(exc).__name__})
    if allow_submit:
        if os.environ.get('GNOSIS_ENABLE_IBM_AUTO_SUBMIT')!='YES':
            report['needs_review'].append({'reason':'auto_submission_env_disabled'})
        elif not report['needs_review']:
            inflight = db.execute("SELECT count(*) FROM ibm_future_jobs WHERE status IN ('submitting','submitted','running','result_ready')").fetchone()[0]
            max_inflight = min(10,max(1,int(os.environ.get('GNOSIS_IBM_MAX_INFLIGHT','1'))))
            if inflight >= max_inflight:
                report['submitted']={'status':'capacity_hold','inflight':inflight,'max_inflight':max_inflight}
                return report
            # Exactly one new, explicitly authorized paid job per cycle, and
            # only if the claim is from an already funded and queued request.
            try:report['submitted']=submit_one(db,backend_name=backend,enable_live=True)
            except Exception as exc:
                report['needs_review'].append({'reason':'submission_requires_reconciliation',
                                               'error_type':type(exc).__name__})
    report['mail']=dispatch_one(db,allow_admin_trial=allow_admin_trial_email)
    return report
