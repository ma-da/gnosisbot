"""Durable, event-triggered local post-commit processing. No periodic polling or QPU calls."""
from __future__ import annotations
import os, logging, threading, fcntl, json
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from .config import get_settings
from .db import connect
from .certificate_validation import POLICY,need
from .certificate_store import ROW_SQL,issue,verify_record,stamp
from .certificate_automation import checkpoint_key,export_checkpoint
from . import gqtp

log=logging.getLogger(__name__)
_guard=threading.Lock()
_executor=None
_active=False
_dirty=False

def enabled():return os.environ.get('GNOSIS_ENABLE_READING_COMPLETION_EVENTS')=='YES'

def enqueue(db,row):
    """Called within existing settlement transaction, after GQTP receipt."""
    if not enabled() or row['service_id'] not in POLICY:return False
    need(db.in_transaction,'completion_event_requires_transaction')
    db.execute('''INSERT OR IGNORE INTO reading_completion_events
       (request_id,consultation_id,notify_requested,state,created_at,updated_at)
       VALUES(?,?,?,'pending',?,?)''',(row['request_id'],row['consultation_id'],
       int(os.environ.get('GNOSIS_ENABLE_COMPLETION_EMAIL')=='YES'),stamp(),stamp()))
    return True

@contextmanager
def processing_lock(data):
    # Serialize across API and external IBM worker processes. No time-based wakeups.
    path=data/'certificates-private'/'completion.lock'
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:os.close(fd)

def _eligible_pending(db):
    # Future's durable IBM job completion transition follows financial settlement.
    return db.execute('''SELECT e.* FROM reading_completion_events e JOIN service_requests s USING(request_id)
       WHERE e.state='pending' AND (s.service_id NOT LIKE '%.quantum_future' OR EXISTS
       (SELECT 1 FROM ibm_future_jobs j WHERE j.request_id=e.request_id AND j.status='completed'))
       ORDER BY e.created_at,e.request_id LIMIT 20''').fetchall()

def process_one(db,event,data):
    from .completion_outbox import enqueue_after_settlement, suppress_legacy
    rid=event['request_id'];cid=event['consultation_id']
    try:
        row=db.execute(ROW_SQL+' AND s.request_id=?',(rid,)).fetchone();need(row is not None and row['consultation_id']==cid,'missing_settled_reading')
        q=db.execute('SELECT seq FROM gqtp_receipts WHERE consultation_id=?',(cid,)).fetchone();need(q is not None,'missing_completion_receipt')
        env=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size>=? ORDER BY tree_size DESC LIMIT 1',(q[0],)).fetchone()
        if env is None:
            key=checkpoint_key(data,data/'transparency/signing.key');cp=gqtp.checkpoint(db,key)
        else:cp=json.loads(env[0])
        # Export repair also runs after a crash between checkpoint commit and export.
        pinned=(data/'transparency/public/public-key.txt').read_text().strip()
        need(gqtp.verify_checkpoint(cp,pinned),'invalid_checkpoint');export_checkpoint(data,cp)
        result=issue(db,row,data,apply=True)
        need(result['state'] in ('issued','already_issued'),'certificate_not_ready')
        cert_id=result['certificate_id']
        db.execute('BEGIN IMMEDIATE')
        try:
            fresh=db.execute('SELECT * FROM reading_completion_events WHERE request_id=?',(rid,)).fetchone()
            need(fresh is not None and fresh['state']=='pending','event_state_changed')
            cert=db.execute('SELECT * FROM reading_certificates WHERE certificate_id=? AND consultation_id=?',(cert_id,cid)).fetchone()
            need(cert is not None and verify_record(cert,data),'invalid_certificate')
            if fresh['notify_requested']:
                account=db.execute('SELECT account_id FROM consultations WHERE consultation_id=?',(cid,)).fetchone()[0]
                enqueue_after_settlement(db,request_id=rid,consultation_id=cid,account_id=account)
                suppress_legacy(db,rid)
            db.execute("UPDATE reading_completion_events SET state='ready',certificate_id=?,attempts=attempts+1,last_error=NULL,updated_at=? WHERE request_id=?",(cert_id,stamp(),rid))
            db.commit()
        except Exception:db.rollback();raise
        return 'ready'
    except Exception as exc:
        # Settlement already committed; retain durable, operator-recoverable failure.
        if db.in_transaction:db.rollback()
        db.execute("UPDATE reading_completion_events SET state='blocked',attempts=attempts+1,last_error=?,updated_at=? WHERE request_id=? AND state='pending'",(type(exc).__name__,stamp(),rid))
        log.warning('Reading completion blocked: %s',type(exc).__name__)
        return 'blocked'

def drain(db,data,*,transport=None,send=True):
    from .completion_outbox import dispatch_one,flag_stale_claims_for_review
    report={'ready':0,'blocked':0,'mail':{}}
    with processing_lock(data):
        # Only pending work already committed; no historical scan.
        while True:
            rows=_eligible_pending(db)
            if not rows:break
            for row in rows:
                state=process_one(db,row,data);report[state]+=1
        if send:
            flag_stale_claims_for_review(db)
            # Snapshot pending IDs; no spin if contact is revoked or mail disabled.
            ids=[r[0] for r in db.execute('''SELECT o.request_id FROM gnosis_completion_outbox o JOIN reading_completion_events e USING(request_id)
                   WHERE o.status='pending' AND e.state='ready' AND e.notify_requested=1 ORDER BY o.created_at,o.request_id''')]
            for rid in ids:
                result=dispatch_one(db,transport=transport,request_id=rid)
                state=result['status'];report['mail'][state]=report['mail'].get(state,0)+1
                if state in ('disabled','not_configured'):break
    return report

def _run():
    global _active,_dirty
    while True:
        with _guard:_dirty=False
        try:
            settings=get_settings()
            with closing(connect(settings.db_path)) as db:drain(db,settings.data_dir)
        except Exception as exc:log.error('Reading completion processing failed: %s',type(exc).__name__)
        with _guard:
            if not _dirty:_active=False;return
        # A new actual event arrived during processing. This is not a timer.

def wake():
    global _active,_dirty,_executor
    if not enabled():return
    try:
        with _guard:
            _dirty=True
            if _active:return
            if _executor is None:_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='gnosis-completion')
            _active=True
            try:_executor.submit(_run)
            except Exception:_active=False;raise
    except Exception as exc:log.error('Reading completion wake failed: %s',type(exc).__name__)

def wake_for(db):
    """Never process a fixture/alternate database through the configured live worker."""
    if not enabled():return
    try:
        from pathlib import Path
        actual=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
        if actual and Path(actual).resolve()==get_settings().db_path:wake()
    except Exception as exc:log.error('Reading completion wake failed: %s',type(exc).__name__)
