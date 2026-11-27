"""Atomic, idempotent consultation credit reservations and settlement.

No provider execution occurs here. Only trusted backend workers should call
settle/fail after independently validating allocation or hardware results.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from .registry import SERVICES
from .research import project_completed
from .identity import iso, now

class TransactionError(ValueError):
    code = 'invalid_request'

class FutureCapacityError(TransactionError):
    code='future_capacity_unavailable'

class InsufficientCredits(TransactionError):
    code = 'insufficient_credits'

class CooldownActive(TransactionError):
    code = 'cooldown_active'
    def __init__(self, next_eligible_at):
        super().__init__(f'Next consultation eligible at {next_eligible_at}')
        self.next_eligible_at = next_eligible_at

class RequestConflict(TransactionError):
    code = 'idempotency_conflict'


def _begin(db):
    db.execute('BEGIN IMMEDIATE')

def _record_ledger(db, account_id, kind, delta, reserved_delta, idem, consultation_id):
    db.execute('''INSERT INTO credit_ledger
       (entry_id,account_id,kind,available_delta,reserved_delta,idempotency_key,consultation_id,source)
       VALUES(?,?,?,?,?,?,?,?)''',
       (uuid4().hex,account_id,kind,delta,reserved_delta,idem,consultation_id,'consultation'))

def _digest(account_id, service_id, question, inquiry_style, consent):
    payload = [account_id,service_id,question,inquiry_style,bool(consent)]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def _get_request(db, request_id):
    row=db.execute('''SELECT r.*, c.account_id, c.question, c.inquiry_style, c.status AS consultation_status,
        ca.available, ca.reserved, (ca.available + ca.reserved) AS total_credits,
        (SELECT admission_seq FROM consultation_admissions WHERE request_id=r.request_id) AS admission_seq FROM service_requests r
        JOIN consultations c ON c.consultation_id=r.consultation_id
        JOIN credit_accounts ca ON ca.account_id=c.account_id
        WHERE r.request_id=?''',(request_id,)).fetchone()
    return dict(row) if row else None

def begin_consultation(db, *, account_id, service_id, idempotency_key,
                       question='', inquiry_style='direct', research_publication_consent=False,
                       cooldown_seconds=None, admin_future_trial=False):
    """Reserve credits; for no-cost services record pending request without debit.

    Idempotent retries return the same record before cooldown or balance checks.
    A pending request must be completed/failed by a trusted provider worker.
    """
    if service_id not in SERVICES or service_id=='iching.classic' or service_id=='iching.ai_enhancement':
        raise TransactionError('Service not available through consultation begin')
    if not isinstance(account_id,str) or len(account_id)!=64:
        raise TransactionError('Invalid account')
    if not isinstance(idempotency_key,str) or not 16<=len(idempotency_key)<=128:
        raise TransactionError('Idempotency key must contain 16..128 characters')
    if not isinstance(question,str) or len(question)>2000:
        raise TransactionError('Question must be at most 2000 characters')
    if inquiry_style not in ('direct','meditative') or type(research_publication_consent) is not bool:
        raise TransactionError('Invalid consultation metadata')
    policy=SERVICES[service_id]
    cooldown = policy.cooldown_seconds if cooldown_seconds is None else cooldown_seconds
    if type(cooldown) is not int or not 0<=cooldown<=86400:
        raise TransactionError('Invalid cooldown')
    digest = _digest(account_id,service_id,question,inquiry_style,research_publication_consent)
    stamp=iso(now())
    try:
        _begin(db)
        existing=db.execute('SELECT request_id,request_hash FROM service_requests WHERE idempotency_key=?',
                            (idempotency_key,)).fetchone()
        if existing:
            if existing['request_hash']!=digest:
                raise RequestConflict('Idempotency key reused with different request')
            result=_get_request(db,existing['request_id'])
            db.commit()
            return result
        account=db.execute('''SELECT a.is_admin,a.status,ca.available FROM accounts a
             JOIN credit_accounts ca ON ca.account_id=a.account_id WHERE a.account_id=?''',
             (account_id,)).fetchone()
        if not account or account['status']!='active':
            raise TransactionError('Account not active')
        # Admins bypass cooldown ONLY. Paid provider executions still consume credits.
        if admin_future_trial:
            from .future_trial import allowed
            if not allowed(dict(account),service_id):
                raise TransactionError('Future service authorization required')
        if account['available']<max(policy.min_balance,policy.credits):
            raise InsufficientCredits('Insufficient available credits')
        if not account['is_admin'] and cooldown:
            prev=db.execute('SELECT next_eligible_at FROM cooldowns WHERE account_id=? AND cooldown_scope=?',
                            (account_id,'consultation')).fetchone()
            if prev and prev['next_eligible_at']>stamp:
                raise CooldownActive(prev['next_eligible_at'])
        cid=uuid4().hex
        rid=uuid4().hex
        until=None
        db.execute('''INSERT INTO consultations(consultation_id,account_id,application_id,
          question,inquiry_style,status,created_at,research_publication_consent)
          VALUES(?,?,?,?,?,'pending',?,?)''',
          (cid,account_id,('runes' if service_id.startswith('runes.') else 'iching'),question,inquiry_style,stamp,int(research_publication_consent)))
        if policy.credits:
            db.execute('UPDATE credit_accounts SET available=available-?,reserved=reserved+? WHERE account_id=?',
                       (policy.credits,policy.credits,account_id))
            _record_ledger(db,account_id,'reserve',-policy.credits,policy.credits,'reserve:'+rid,cid)
        if not account['is_admin'] and cooldown:
            until=iso(now()+timedelta(seconds=cooldown))
            db.execute('''INSERT INTO cooldowns(account_id,cooldown_scope,next_eligible_at)
              VALUES(?,'consultation',?) ON CONFLICT(account_id,cooldown_scope)
              DO UPDATE SET next_eligible_at=excluded.next_eligible_at''',(account_id,until))
        db.execute('''INSERT INTO service_requests(request_id,consultation_id,service_id,provider,status,
          idempotency_key,credits_cost,started_at,request_hash,cooldown_until)
          VALUES(?,?,?,?,'pending',?,?,?,?,?)''',
          (rid,cid,service_id,policy.provider,idempotency_key,policy.credits,stamp,digest,until))
        # SQLite BEGIN IMMEDIATE serializes authorization and funding checks.
        # The assigned ticket records COMMITTED admission order, not network arrival order.
        db.execute('INSERT INTO consultation_admissions(request_id,account_id,admitted_at) VALUES(?,?,?)',
                   (rid,account_id,stamp))
        if admin_future_trial:
            from .future_auto_policy import production_enabled
            db.execute("INSERT INTO ibm_future_jobs(request_id,status,created_at,updated_at,metadata_json) VALUES(?,'queued',?,?,?)",(rid,stamp,stamp,json.dumps({'controlled_trial':True,'production':production_enabled()})))
        if admin_future_trial:
            from .future_auto_policy import allocate
            allocate(db,rid)
        result=_get_request(db,rid)
        db.commit()
        if admin_future_trial:
            from .future_automation import wake_for
            wake_for(db)
        return result
    except Exception:
        db.rollback()
        raise


def finish_request(db, request_id, *, success, result_json=None, provenance_json=None, schema_version='gnosis.reading.v1', private_rune_archive=None):
    """Settle or release a pending request exactly once. Provider-neutral.

    On success a full reading and provenance are required; on failure they must
    be absent. No QPU/QRNG requests or email notifications are triggered here.
    """
    if type(success) is not bool:
        raise TransactionError('success must be boolean')
    if success:
        if not isinstance(result_json,dict) or not isinstance(provenance_json,dict):
            raise TransactionError('Successful request requires reading and provenance dicts')
        # No billable completion without an actual six-line cast and a provenance record.
        # Avoid boolean integers (True/False) masquerading as line values.
        # M5B: application-specific validation after authoritative request lookup.
        if not provenance_json:
            raise TransactionError('Completed reading requires nonempty provenance')
    elif result_json is not None or provenance_json is not None:
        raise TransactionError('Failed request cannot contain a result')
    try:
        _begin(db)
        row=_get_request(db,request_id)
        if not row:
            raise TransactionError('Unknown request')
        is_rune = row['service_id'].startswith('runes.')
        if success and not is_rune:
            lines = result_json.get('lines')
            if not isinstance(lines,list) or len(lines)!=6 or any(type(x) is not int or x not in (6,7,8,9) for x in lines):
                raise TransactionError('Completed reading requires six valid I Ching line values')
        target='completed' if success else 'failed'
        if row['status']!='pending':
            if row['status']!=target:
                raise RequestConflict('Request has already reached a different terminal state')
            db.commit()
            return row
        stamp=iso(now())
        credits=row['credits_cost']
        if credits:
            if row['reserved']<credits:
                raise TransactionError('Reserved balance inconsistent')
            db.execute('UPDATE credit_accounts SET reserved=reserved-? WHERE account_id=?',
                       (credits,row['account_id']))
            if success:
                _record_ledger(db,row['account_id'],'settle',0,-credits,'settle:'+request_id,row['consultation_id'])
            else:
                db.execute('UPDATE credit_accounts SET available=available+? WHERE account_id=?',
                           (credits,row['account_id']))
                _record_ledger(db,row['account_id'],'release',credits,-credits,'release:'+request_id,row['consultation_id'])
        if success:
            db.execute('''INSERT INTO reading_results(result_id,consultation_id,schema_version,
                reading_json,provenance_json,created_at) VALUES(?,?,?,?,?,?)''',
                (uuid4().hex,row['consultation_id'],schema_version,
                 json.dumps(result_json,ensure_ascii=False,separators=(',',':')),
                 json.dumps(provenance_json,ensure_ascii=False,separators=(',',':')),stamp))
            if is_rune:
                from .rune_production import persist_completed
                persist_completed(db,row,result_json,provenance_json,private_rune_archive,stamp,schema_version)
            else:
                project_completed(db,row['consultation_id'],result_json,provenance_json,stamp)
        else:
            if is_rune:
                if row['service_id'].endswith('.quantum_past'):
                    from .rune_past_inventory import void_failed_hold
                    void_failed_hold(db,row)
                db.execute("UPDATE rune_executions SET status='failed',updated_at=? WHERE request_id=?",(stamp,request_id))
            # Release cooldown only if this failed request still owns the current deadline.
            # Never erase a later consultation's cooldown.
            db.execute('DELETE FROM cooldowns WHERE account_id=? AND cooldown_scope=? AND next_eligible_at=?',
                       (row['account_id'],'consultation',row['cooldown_until']))
        db.execute('UPDATE consultations SET status=?,finished_at=? WHERE consultation_id=?',
                   (target,stamp,row['consultation_id']))
        db.execute('UPDATE service_requests SET status=?,completed_at=? WHERE request_id=?',
                   (target,stamp,request_id))
        # M4D: durable notification event in the SAME transaction as successful settlement.
        # No Resend network I/O or HTML operation happens inside this transaction.
        from .reading_completion import enabled as completion_events_enabled, enqueue as enqueue_completion, wake_for as wake_completion
        if success and row['service_id']=='iching.quantum_future' and not completion_events_enabled():
            from .completion_outbox import enqueue_after_settlement
            enqueue_after_settlement(db,request_id=request_id,
                 consultation_id=row['consultation_id'], account_id=row['account_id'])
        queued=False
        if success:
            from .gqtp import record_completion
            record_completion(db,row['consultation_id'])
            queued=enqueue_completion(db,row)
        result=_get_request(db,request_id)
        db.commit()
        if queued and not row['service_id'].endswith('.quantum_future'):wake_completion(db)
        return result
    except Exception:
        db.rollback()
        raise
