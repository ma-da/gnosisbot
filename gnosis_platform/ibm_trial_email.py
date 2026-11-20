"""Operator-only Resend completion notification for a verified test recipient.

Never accepts an email from a request body or leaks private questions.
This is a bridge for the administrator's first end-to-end reading; production
must use verified, encrypted account contacts and an audited notification outbox.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def ensure_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ibm_trial_email_notifications (
      request_id TEXT PRIMARY KEY REFERENCES service_requests(request_id),
      consultation_id TEXT NOT NULL,
      resend_idempotency_key TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL CHECK(status IN ('claimed','sent','needs_review')),
      provider_message_id TEXT,
      claimed_at TEXT NOT NULL,
      sent_at TEXT
    )''')


def prepared_message(*, consultation_id, recipient, sender, base_url):
    if not base_url.startswith('https://') or '\n' in base_url or '\r' in base_url:
        raise ValueError('GNOSIS_PUBLIC_BASE_URL must use HTTPS')
    if '@' not in recipient or any(x in recipient for x in '\r\n'):
        raise ValueError('Invalid test recipient')
    if '@' not in sender or any(x in sender for x in '\r\n'):
        raise ValueError('Invalid sender')
    url=base_url.rstrip('/')+'/reading-history.html'
    return {'from': sender, 'to': [recipient],
            'subject': 'Your Gnosis quantum reading is ready',
            'text': 'Your IBM quantum reading has completed. Sign in to your Gnosis account to view your reading and its 128 measurements.\n\n'+url+'\n\nThis email does not contain your private inquiry.'}


def submit_resend(*, api_key, message, idem_key, transport=None):
    if not api_key or not api_key.startswith("re_"):
        raise ValueError("Missing or invalid RESEND_API_KEY")

    req = Request(
        "https://api.resend.com/emails",
        data=json.dumps(message, separators=(",", ":")).encode("utf8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "GnosisBot/1.0 (+https://gnosis.bot)",
            "Accept": "application/json",
            "Idempotency-Key": idem_key,
        },
        method="POST",
    )

    opener = transport or urlopen

    with opener(req, timeout=20) as response:
        parsed = json.loads(response.read().decode("utf8"))

    if (
        not isinstance(parsed, dict)
        or not isinstance(parsed.get("id"), str)
        or not parsed["id"]
    ):
        raise RuntimeError("Resend did not return an email identifier")

    return parsed["id"]


def send_completed_trial(db, request_id, *, transport=None):
    if os.getenv('GNOSIS_ENABLE_TRIAL_EMAIL')!='YES':
        raise RuntimeError('Trial email disabled; set GNOSIS_ENABLE_TRIAL_EMAIL=YES')
    recipient=os.environ['GNOSIS_TEST_NOTIFICATION_EMAIL']
    sender=os.environ['GNOSIS_RESEND_FROM']
    api_key=os.environ['RESEND_API_KEY']
    base=os.environ.get('GNOSIS_PUBLIC_BASE_URL','https://gnosis.bot')
    db.execute('BEGIN IMMEDIATE')
    try:
        ensure_table(db)
        row=db.execute('''SELECT r.request_id,r.consultation_id,r.status,c.account_id,
          j.status AS job_status
          FROM service_requests r JOIN consultations c ON c.consultation_id=r.consultation_id
          JOIN ibm_future_jobs j ON j.request_id=r.request_id
          JOIN reading_results rr ON rr.consultation_id=r.consultation_id
          WHERE r.request_id=? AND r.service_id='iching.quantum_future'
            AND r.credits_cost=10 AND r.status='completed' AND c.status='completed' ''',(request_id,)).fetchone()
        if not row or row['job_status']!='completed':
            raise ValueError('A fully settled IBM Future reading is required before notification')
        existing=db.execute('SELECT * FROM ibm_trial_email_notifications WHERE request_id=?',(request_id,)).fetchone()
        if existing:
            db.commit()
            return {'status':existing['status'],'provider_message_id':existing['provider_message_id'],
                    'note':'Already claimed; never automatically resend an ambiguous request'}
        idem='gnosis-ibm-trial-complete-'+row['consultation_id']
        db.execute('''INSERT INTO ibm_trial_email_notifications
          (request_id,consultation_id,resend_idempotency_key,status,claimed_at)
          VALUES(?,?,?,'claimed',?)''',(request_id,row['consultation_id'],idem,now()))
        db.commit()
    except Exception:
        db.rollback();raise
    msg=prepared_message(consultation_id=row['consultation_id'], recipient=recipient,
                         sender=sender,base_url=base)
    try:
        message_id=submit_resend(api_key=api_key,message=msg,idem_key=idem,transport=transport)
    except Exception:
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute("UPDATE ibm_trial_email_notifications SET status='needs_review' WHERE request_id=? AND status='claimed'",(request_id,))
            db.commit()
        except Exception:
            db.rollback();raise
        raise
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''UPDATE ibm_trial_email_notifications SET status='sent',
          provider_message_id=?,sent_at=? WHERE request_id=? AND status='claimed' ''',
          (message_id,now(),request_id))
        db.commit()
    except Exception:
        db.rollback();raise
    return {'status':'sent','provider_message_id':message_id}
