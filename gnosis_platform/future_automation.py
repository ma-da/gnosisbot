"""Administrator canary worker; no idle database/provider polling.

SQLite admission and paid claims remain authoritative. Only acknowledged job
IDs may be retrieved automatically. No automatic retry of paid submissions.
"""
import fcntl, json, logging, os, threading, time
from pathlib import Path
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from .config import get_settings
from .db import connect
from .future_auto_policy import enabled, production_enabled, controlled_enabled
from . import future_execution as execution
from .ibm_worker import settle_staged
from .ibm_future_queue import stamp

log=logging.getLogger(__name__)
_event=threading.Event()
_stop=threading.Event()
_thread=None
_guard=threading.Lock()

@contextmanager
def request_lock(data,rid):
    if len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid):raise ValueError('Invalid Future request ID')
    directory=Path(data)/'certificates-private'
    fd=os.open(directory/('future-'+rid+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)

def candidates(db):
    return [r[0] for r in db.execute("""SELECT j.request_id FROM future_auto_requests a JOIN ibm_future_jobs j USING(request_id)
      WHERE a.paused_reason IS NULL AND (j.status IN ('queued','submitting','submitted','running','result_ready')
      OR (j.status IN ('completed','failed') AND j.external_job_id IS NOT NULL AND COALESCE(json_extract(j.metadata_json,'$.provider_usage.usage_final'),0)=0)) ORDER BY j.created_at,j.request_id""")]

def pause(db,rid,reason):
    db.execute('UPDATE future_auto_requests SET paused_reason=? WHERE request_id=?',(reason,rid))
    log.warning('Future automation paused request %s: %s',rid,reason)

def step(db,data,rid):
    """Return whether further monitoring is needed. No paid retry."""
    try:
        with request_lock(data,rid):
            return _step(db,data,rid)
    except BlockingIOError:
        return True

def pending_usage(row):
    return (row['status'] in ('completed','failed') and bool(row['external_job_id']) and
            not (json.loads(row['metadata_json'] or '{}').get('provider_usage') or {}).get('usage_final'))

def retry(db,rid,reason):
    db.execute('UPDATE future_auto_requests SET error_count=error_count+1 WHERE request_id=?',(rid,))
    if db.execute('SELECT error_count FROM future_auto_requests WHERE request_id=?',(rid,)).fetchone()[0]>=5:
        pause(db,rid,reason);return False
    return True

def collect_usage(db,rid,row):
    # Billing metrics can arrive after the reading. Never hold up certificate/email.
    try:
        job=execution.runtime().job(row['external_job_id'])
        execution.need(job.job_id()==row['external_job_id'] and job.backend().name==row['backend'],'Remote job mismatch')
        result=execution.usage(db,rid,job)
        if not result['usage_final']:return retry(db,rid,'usage_not_final')
        db.execute('UPDATE future_auto_requests SET error_count=0 WHERE request_id=?',(rid,))
        return False
    except Exception as exc:return retry(db,rid,'usage_'+type(exc).__name__)

def _step(db,data,rid):
    row=execution.job_row(db,rid)
    a=db.execute('SELECT a.*,p.reviewed_seconds,p.revoked_at,p.expires_at FROM future_auto_requests a LEFT JOIN future_auto_permits p USING(permit_id) WHERE request_id=?',(rid,)).fetchone()
    if a is None or a['paused_reason']:return False
    state=row['status'];spool=Path(data)/'ibm-results-restricted'
    if state in ('completed','failed'):return collect_usage(db,rid,row) if pending_usage(row) else False
    if state=='needs_reconciliation':return False
    if state=='submitting':pause(db,rid,'submission_outcome_uncertain');return False
    if state=='queued':
        production=a['permit_id'] is None
        if production and not production_enabled():return False  # resume on re-enable/startup
        if not production and (not controlled_enabled() or a['revoked_at'] or a['expires_at']<=stamp()):pause(db,rid,'authorization_inactive');return False
        if production and row['request_status']=='failed':
            db.execute("UPDATE ibm_future_jobs SET status='failed',failure_code='pre_submission_failed',finished_at=?,updated_at=? WHERE request_id=? AND status='queued'",(stamp(),stamp(),rid));return False
        try:execution.submit(db,rid,authorized=True,remaining=a['reviewed_seconds'],automatic=True)
        except Exception as exc:
            latest=execution.job_row(db,rid)['status']
            if production and latest=='queued':
                # No paid claim was made. Refund, rather than strand funded users.
                from .transactions import finish_request
                finish_request(db,rid,success=False)
                db.execute("UPDATE ibm_future_jobs SET status='failed',failure_code='pre_submission_failed',finished_at=?,updated_at=? WHERE request_id=? AND status='queued'",(stamp(),stamp(),rid))
                log.warning('Future pre-submission failed for %s: %s',rid,type(exc).__name__)
                return False
            pause(db,rid,'submission_outcome_uncertain' if latest=='submitting' else 'submission_preflight_'+type(exc).__name__)
            return False
        return True
    # A funded request may be settled before the final local job transition.
    # Use the existing idempotent settle path to recover that exact reading.
    try:
        if state in ('submitted','running'):
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['submitted_at'].replace('Z','+00:00'))).total_seconds()
            if age>7200:pause(db,rid,'monitoring_window_elapsed');return False
            execution.retrieve(db,rid,spool)
            row=execution.job_row(db,rid);state=row['status']
        if state=='result_ready':settle_staged(db,rid,spool=spool)
        db.execute('UPDATE future_auto_requests SET error_count=0 WHERE request_id=?',(rid,))
        latest=execution.job_row(db,rid)
        return latest['status'] in ('submitted','running','result_ready') or pending_usage(latest)
    except Exception as exc:
        return retry(db,rid,'retrieval_or_settlement_'+type(exc).__name__)

def _run():
    due={};delays={};s=get_settings()
    while not _stop.is_set():
        if _event.is_set():
            _event.clear()
            try:
                with closing(connect(s.db_path)) as db:
                    for rid in candidates(db):due.setdefault(rid,time.monotonic())
            except Exception:log.exception('Future automation recovery scan failed')
        now=time.monotonic()
        for rid,t in list(due.items()):
            if _stop.is_set():return
            if t>now:continue
            try:
                with closing(connect(s.db_path)) as db:more=step(db,s.data_dir,rid)
            except Exception as exc:
                # Unexpected local errors are not permission to issue paid work.
                log.error('Future worker request %s stopped: %s',rid,type(exc).__name__);more=False
            if more:
                delay=delays.get(rid,2);due[rid]=time.monotonic()+delay;delays[rid]=min(delay*2,60)
            else:due.pop(rid,None);delays.pop(rid,None)
        if _stop.is_set():return
        timeout=max(0,min(due.values())-time.monotonic()) if due else None
        _event.wait(timeout)

def start():
    global _thread
    # One startup recovery scan even when new admissions are disabled.
    with _guard:
        if _thread and _thread.is_alive():return
        _stop.clear();_event.set();_thread=threading.Thread(target=_run,name='gnosis-future-auto',daemon=True);_thread.start()

def stop():
    _stop.set();_event.set()
    if _thread:_thread.join(timeout=2)

def wake_for(db):
    # Only the running API process owns this worker. CLI/fixture commits do not
    # start background paid operations. Restart scans committed work once.
    try:
        if not enabled() or not _thread or not _thread.is_alive():return
        actual=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
        if actual and Path(actual).resolve()==get_settings().db_path:_event.set()
    except Exception as exc:log.error('Future automation wake failed: %s',type(exc).__name__)
