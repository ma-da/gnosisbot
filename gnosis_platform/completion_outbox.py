"""Durable IBM completion notifications. No network calls in settlement transactions.

`enqueue_after_settlement` is called *inside* transactions.finish_request BEGIN IMMEDIATE,
so a billable completed reading and its notification event commit atomically.
A claimed Resend request is never blindly retried after an ambiguous network failure.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.error import HTTPError


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def enqueue_after_settlement(db, *, request_id, consultation_id, account_id):
    """Caller owns an open SQLite transaction. No BEGIN/COMMIT here."""
    account = db.execute('''SELECT c.account_id, r.service_id, r.status, c.status AS consultation_status,a.is_admin
       FROM service_requests r JOIN consultations c ON c.consultation_id=r.consultation_id
       JOIN accounts a ON a.account_id=c.account_id
       WHERE r.request_id=? AND r.consultation_id=?''', (request_id, consultation_id)).fetchone()
    from .reading_completion import enabled
    from .certificate_validation import POLICY
    allowed = set(POLICY) if enabled() else {'iching.quantum_future'}
    if (not account or account['account_id'] != account_id
        or account['service_id'] not in allowed
        or account['status'] != 'completed' or account['consultation_status'] != 'completed'):
        raise ValueError('Completion event requires a settled IBM Future consultation')
    if not db.execute('SELECT 1 FROM reading_results WHERE consultation_id=?',(consultation_id,)).fetchone():
        raise ValueError('Completion event requires saved reading')
    contact = db.execute('''SELECT contact_id FROM account_contacts WHERE account_id=?
       AND verified_at IS NOT NULL AND revoked_at IS NULL
       ORDER BY verified_at DESC,created_at DESC LIMIT 1''',(account_id,)).fetchone()
    cid = contact['contact_id'] if contact else None
    trial_ok=(not enabled() and bool(account['is_admin']) and os.environ.get('GNOSIS_ENABLE_TRIAL_EMAIL')=='YES'
              and bool(os.environ.get('GNOSIS_TEST_NOTIFICATION_EMAIL')))
    status = 'pending' if cid or trial_ok else 'awaiting_contact'
    db.execute('''INSERT OR IGNORE INTO gnosis_completion_outbox
      (request_id,consultation_id,account_id,contact_id,status,idempotency_key,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?)''',
      (request_id,consultation_id,account_id,cid,status,
       'gnosis-complete-'+consultation_id,stamp(),stamp()))


def activate_for_verified_account(db, account_id, contact_id):
    """Caller owns a transaction; enqueue pending unsent notices once contact is verified."""
    db.execute('''UPDATE gnosis_completion_outbox SET contact_id=?, status='pending',updated_at=?
       WHERE account_id=? AND status IN ('awaiting_contact','pending') ''',(contact_id,stamp(),account_id))


def reconcile_completed(db, *, request_id):
    """Operator opt-in backfill of a previously settled IBM request. No mail is sent here."""
    row = db.execute('''SELECT c.account_id,c.consultation_id,r.status
      FROM service_requests r JOIN consultations c ON c.consultation_id=r.consultation_id
      WHERE r.request_id=? AND r.service_id='iching.quantum_future' AND c.status='completed' ''',
      (request_id,)).fetchone()
    if not row or row['status'] != 'completed':
        raise ValueError('Request is not completed')
    db.execute('BEGIN IMMEDIATE')
    try:
        enqueue_after_settlement(db,request_id=request_id,consultation_id=row['consultation_id'],account_id=row['account_id'])
        # Legacy administrator trial may already have sent a notice through the
        # original single-shot bridge. Never send that completed notice twice.
        legacy_table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ibm_trial_email_notifications'").fetchone()
        if legacy_table:
            old=db.execute("SELECT status,provider_message_id FROM ibm_trial_email_notifications WHERE request_id=?",(request_id,)).fetchone()
            if old:
                db.execute("UPDATE gnosis_completion_outbox SET status='sent',provider_message_id=?,sent_at=?,updated_at=? WHERE request_id=? AND status!='sent'",
                    (old['provider_message_id'],stamp(),stamp(),request_id)) if old['status']=='sent' else db.execute("UPDATE gnosis_completion_outbox SET status='needs_review',last_error='legacy_notification_claimed',updated_at=? WHERE request_id=? AND status!='sent'",(stamp(),request_id))
        db.commit()
    except Exception:
        db.rollback(); raise


def suppress_legacy(db,request_id):
    """A legacy trial claim or send must never produce a second completion email."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ibm_trial_email_notifications'").fetchone():return
    old=db.execute('SELECT status,provider_message_id,sent_at FROM ibm_trial_email_notifications WHERE request_id=?',(request_id,)).fetchone()
    if old:
        if old['status']=='sent':
            db.execute("UPDATE gnosis_completion_outbox SET status='sent',provider_message_id=?,sent_at=?,updated_at=? WHERE request_id=? AND status NOT IN ('sent','sending')",(old['provider_message_id'],old['sent_at'] or stamp(),stamp(),request_id))
        else:
            db.execute("UPDATE gnosis_completion_outbox SET status='needs_review',last_error='legacy_notification_claimed',updated_at=? WHERE request_id=? AND status NOT IN ('sent','sending')",(stamp(),request_id))


def _claim_one(db, *, allow_admin_trial, request_id=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        from .reading_completion import enabled
        gate = " AND EXISTS(SELECT 1 FROM reading_completion_events e WHERE e.request_id=o.request_id AND e.state='ready' AND e.notify_requested=1)" if enabled() else " AND NOT EXISTS(SELECT 1 FROM reading_completion_events e WHERE e.request_id=o.request_id)" if db.execute("SELECT 1 FROM sqlite_master WHERE name='reading_completion_events'").fetchone() else ''
        row = db.execute('''SELECT o.*, a.is_admin, ac.email_encrypted,
          ac.verified_at, ac.revoked_at
          FROM gnosis_completion_outbox o
          JOIN accounts a ON a.account_id=o.account_id
          LEFT JOIN account_contacts ac ON ac.contact_id=o.contact_id AND ac.account_id=o.account_id
          WHERE o.status='pending' AND a.status='active' AND (? IS NULL OR o.request_id=?) '''+gate+' ORDER BY o.created_at,o.request_id LIMIT 1',(request_id,request_id)).fetchone()
        if not row:
            db.commit();return None
        if row['contact_id'] and (not row['verified_at'] or row['revoked_at']):
            db.execute("UPDATE gnosis_completion_outbox SET status='awaiting_contact',contact_id=NULL WHERE request_id=?",(row['request_id'],))
            db.commit();return None
        if not row['contact_id'] and not (allow_admin_trial and bool(row['is_admin'])):
            db.execute("UPDATE gnosis_completion_outbox SET status='awaiting_contact' WHERE request_id=?",(row['request_id'],))
            db.commit();return None
        db.execute('''UPDATE gnosis_completion_outbox SET status='sending',claimed_at=?,attempts=attempts+1,updated_at=?
            WHERE request_id=? AND status='pending' ''',(stamp(),stamp(),row['request_id']))
        db.commit()
        return dict(row)
    except Exception:
        db.rollback();raise



def flag_stale_claims_for_review(db, *, after_minutes=15):
    """Flag orphaned send attempts after a process crash; NEVER resend automatically."""
    from datetime import timedelta
    limit=(datetime.now(timezone.utc)-timedelta(minutes=after_minutes)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    db.execute('BEGIN IMMEDIATE')
    try:
        cur=db.execute('''UPDATE gnosis_completion_outbox
          SET status='needs_review',last_error='stale_claim_unknown_provider_outcome',updated_at=?
          WHERE status='sending' AND claimed_at<?''',(stamp(),limit))
        db.commit()
        return cur.rowcount
    except Exception:
        db.rollback();raise

def dispatch_one(db, *, transport=None, allow_admin_trial=False, request_id=None):
    """Send one outbox event to Resend. Unknown outcome -> needs_review, no auto-retry.

    Completion mail does NOT contain question, coin bits, QPU identifier or private data.
    """
    if os.environ.get('GNOSIS_ENABLE_COMPLETION_EMAIL') != 'YES':
        return {'status':'disabled'}
    # Check configuration before claiming an email event.
    key = os.environ.get('RESEND_API_KEY')
    sender = os.environ.get('GNOSIS_RESEND_FROM')
    base = os.environ.get('GNOSIS_PUBLIC_BASE_URL', 'https://gnosis.bot')
    if not key or not sender or not base.startswith('https://'):
        return {'status':'not_configured'}
    from .reading_completion import enabled
    event_mode=enabled()
    row = _claim_one(db,allow_admin_trial=allow_admin_trial and not event_mode,request_id=request_id)
    if row is None:return {'status':'none_due'}
    request_id = row['request_id']
    try:
        if row['contact_id']:
            from .account_email import decrypt_email
            recipient = decrypt_email(row['email_encrypted'])
        elif allow_admin_trial and row['is_admin'] and os.environ.get('GNOSIS_ENABLE_TRIAL_EMAIL')=='YES':
            recipient = os.environ['GNOSIS_TEST_NOTIFICATION_EMAIL']
        else:
            raise ValueError('No verified completion-email recipient')
        from .ibm_trial_email import submit_resend
        if event_mode:
            from .reading_results_email import certified_record,prepared_message
            from .config import get_settings
            cert=certified_record(db,request_id,get_settings().data_dir)
            message=prepared_message(cert,recipient=recipient,sender=sender,base_url=base)
            # Recheck address before external transmission; no cross-account contact.
            current=db.execute('SELECT 1 FROM account_contacts WHERE contact_id=? AND account_id=? AND verified_at IS NOT NULL AND revoked_at IS NULL',(row['contact_id'],row['account_id'])).fetchone()
            if not current:raise ValueError('Contact revoked before send')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ibm_trial_email_notifications'").fetchone() and db.execute('SELECT 1 FROM ibm_trial_email_notifications WHERE request_id=?',(request_id,)).fetchone():raise ValueError('Legacy notification exists')
        else:
            from .ibm_trial_email import prepared_message
            message=prepared_message(consultation_id=row['consultation_id'],recipient=recipient,sender=sender,base_url=base)
            message['text']=message['text'].replace('/reading-history.html','/account.html?view=activity&reading='+row['consultation_id'])
        provider_message_id=submit_resend(api_key=key,message=message,
                                           idem_key=row['idempotency_key'],transport=transport)
    except Exception as exc:
        db.execute('BEGIN IMMEDIATE')
        try:
            # Never treat an ambiguous HTTP/network error as proof the email was not sent.
            db.execute('''UPDATE gnosis_completion_outbox SET status='needs_review',last_error=?,updated_at=?
               WHERE request_id=? AND status='sending' ''',(type(exc).__name__,stamp(),request_id))
            db.commit()
        except Exception:
            db.rollback();raise
        return {'status':'needs_review','request_id':request_id,'error_type':type(exc).__name__}
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''UPDATE gnosis_completion_outbox SET status='sent',provider_message_id=?,sent_at=?,updated_at=?
          WHERE request_id=? AND status='sending' ''',
          (provider_message_id,stamp(),stamp(),request_id))
        db.commit()
    except Exception:
        db.rollback();raise
    return {'status':'sent','request_id':request_id,'provider_message_id':provider_message_id}
