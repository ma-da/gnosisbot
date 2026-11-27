"""Explicit bounded automation authorization, separate from public service flags."""
import os, math
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .ibm_future_queue import stamp

SWITCH='GNOSIS_ENABLE_CONTROLLED_FUTURE_AUTO'
PRODUCTION_SWITCH='GNOSIS_ENABLE_QUANTUM_FUTURE'
ALLOWANCE=5.0
MIN_FLOOR=250.0

def production_enabled():
    return (os.getenv(PRODUCTION_SWITCH)=='YES' and
        os.getenv('GNOSIS_ENABLE_READING_COMPLETION_EVENTS')=='YES' and
        all(os.getenv(k)!='YES' for k in (SWITCH,'GNOSIS_ENABLE_IBM_ADMIN_TRIAL','GNOSIS_ENABLE_IBM_AUTO_SUBMIT','GNOSIS_ENABLE_IBM_LIVE_SUBMISSION','GNOSIS_ENABLE_IBM_PILOT')))

def controlled_enabled():
    return (os.getenv(PRODUCTION_SWITCH)!='YES' and os.getenv(SWITCH)=='YES' and
        all(os.getenv(k)=='YES' for k in ('GNOSIS_ALLOW_CONTROLLED_ADMIN_TRIAL','GNOSIS_ENABLE_IBM_ADMIN_TRIAL','GNOSIS_ENABLE_READING_COMPLETION_EVENTS')) and
        all(os.getenv(k)!='YES' for k in ('GNOSIS_ENABLE_IBM_AUTO_SUBMIT','GNOSIS_ENABLE_IBM_PILOT')))

def enabled():
    return production_enabled() or controlled_enabled()

def active(db):
    return db.execute("SELECT * FROM future_auto_permits WHERE revoked_at IS NULL AND expires_at>? ORDER BY created_at DESC LIMIT 1",(stamp(),)).fetchone()

def arm(db, count, remaining, floor):
    if not (type(count) is int and 1<=count<=10 and math.isfinite(remaining) and math.isfinite(floor) and floor>=MIN_FLOOR and remaining>=floor+ALLOWANCE*count):
        raise ValueError('Insufficient reviewed allocation: reserve floor >=250s plus 5s per authorized job required')
    db.execute('BEGIN IMMEDIATE')
    try:
        if active(db) is not None:raise ValueError('Disarm previous permit first')
        if db.execute("SELECT 1 FROM ibm_future_jobs WHERE status IN ('queued','submitting','submitted','running','result_ready','needs_reconciliation') LIMIT 1").fetchone():raise ValueError('Reconcile all outstanding Future jobs before arming')
        pid=uuid4().hex
        exp=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(timespec='milliseconds').replace('+00:00','Z')
        db.execute('INSERT INTO future_auto_permits VALUES(?,?,?,?,?,?,NULL)',(pid,stamp(),exp,remaining,floor,count));db.commit()
        return {'permit_id':pid,'max_jobs':count,'reviewed_seconds':remaining,'reserve_floor':floor,'expires_at':exp}
    except Exception:db.rollback();raise

def disarm(db):
    db.execute("UPDATE future_auto_permits SET revoked_at=? WHERE revoked_at IS NULL",(stamp(),))

def allocate(db,rid):
    # Must share the funded admission transaction. Never attach old manual jobs.
    if not enabled():return
    from .transactions import FutureCapacityError
    if not db.in_transaction:raise RuntimeError('Future permit allocation requires admission transaction')
    if production_enabled():
        db.execute('INSERT INTO future_auto_requests(request_id,permit_id) VALUES(?,NULL)',(rid,))
        return
    p=active(db)
    if p is None or db.execute('SELECT count(*) FROM future_auto_requests WHERE permit_id=?',(p['permit_id'],)).fetchone()[0]>=p['max_jobs']:
        raise FutureCapacityError('Automated Future test allocation exhausted or not armed; no credits reserved')
    db.execute('INSERT INTO future_auto_requests(request_id,permit_id) VALUES(?,?)',(rid,p['permit_id']))

def claim_permit(db,rid,automatic):
    row=db.execute('SELECT a.*,p.revoked_at,p.expires_at,p.reviewed_seconds FROM future_auto_requests a LEFT JOIN future_auto_permits p USING(permit_id) WHERE request_id=?',(rid,)).fetchone()
    if row is not None and row['permit_id'] is None:
        if automatic:
            if not production_enabled() or row['claimed_at'] or row['paused_reason']:raise ValueError('Production submission is not claimable')
            db.execute('UPDATE future_auto_requests SET claimed_at=? WHERE request_id=?',(stamp(),rid))
        elif production_enabled():raise ValueError('Production request is managed automatically; disable new submissions before manual submission')
        return
    if automatic:
        if not controlled_enabled() or row is None or row['claimed_at'] or row['paused_reason'] or row['revoked_at'] or row['expires_at']<=stamp():raise ValueError('No active automatic authorization for request')
        db.execute('UPDATE future_auto_requests SET claimed_at=? WHERE request_id=?',(stamp(),rid))
    elif row is not None and enabled() and row['revoked_at'] is None and row['expires_at']>stamp():
        raise ValueError('Automatic request: disarm before manual submission')
