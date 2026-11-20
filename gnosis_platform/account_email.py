"""User-owned verified notification email, encrypted at rest.

Requires GNOSIS_CONTACT_ENCRYPTION_KEY (persistent Fernet key). Never stores
plaintext email in SQLite; verification tokens stored only as SHA-256 hashes.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime,timedelta,timezone
from uuid import uuid4

EMAIL_RE = re.compile(r'^[^\s@<>]{1,64}@[^\s@<>]{1,190}$')

def stamp(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat(timespec='milliseconds').replace('+00:00','Z')

def cipher():
    from cryptography.fernet import Fernet
    key=os.environ.get('GNOSIS_CONTACT_ENCRYPTION_KEY')
    if not key:
        raise RuntimeError('GNOSIS_CONTACT_ENCRYPTION_KEY must be configured before email enrollment')
    return Fernet(key.encode('ascii'))

def encrypt_email(email):
    return cipher().encrypt(email.encode('utf8'))

def decrypt_email(value):
    return cipher().decrypt(value).decode('utf8')

def canonical(email):
    value = email.strip().lower()
    if len(value)>254 or not EMAIL_RE.fullmatch(value) or '\r' in value or '\n' in value:
        raise ValueError('Invalid email address')
    return value

def email_hash(email):
    # Prevent offline dictionary recovery of addresses from the DB hash alone.
    key=os.environ.get('GNOSIS_CONTACT_ENCRYPTION_KEY')
    if not key:raise RuntimeError('Email encryption unavailable')
    return hmac.new(key.encode(),email.encode('utf8'),hashlib.sha256).hexdigest()

def begin_email_verification(db, *, account_id, email):
    addr=canonical(email)
    # Deny abuse even if verification email send fails. Admin can review delivery logs.
    one_hour_ago=stamp(datetime.now(timezone.utc)-timedelta(hours=1))
    count=db.execute('''SELECT count(*) FROM account_email_challenges
       WHERE account_id=? AND created_at>=?''',(account_id,one_hour_ago)).fetchone()[0]
    if count>=3:raise ValueError('Email verification limit reached (3 per hour)')
    token=secrets.token_urlsafe(32)
    now=datetime.now(timezone.utc)
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''INSERT INTO account_email_challenges
          (challenge_id,account_id,email_encrypted,email_hash,token_hash,created_at,expires_at)
          VALUES(?,?,?,?,?,?,?)''',
          (uuid4().hex,account_id,encrypt_email(addr),email_hash(addr),
           hashlib.sha256(token.encode()).hexdigest(),stamp(now),stamp(now+timedelta(minutes=60))))
        db.commit()
    except Exception:
        db.rollback();raise
    return token,addr

def complete_email_verification(db, *, account_id, token):
    if not isinstance(token,str) or len(token)>256 or len(token)<24:
        raise ValueError('Invalid email verification token')
    digest=hashlib.sha256(token.encode()).hexdigest()
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('''SELECT * FROM account_email_challenges WHERE account_id=?
          AND token_hash=? AND consumed_at IS NULL AND expires_at>? ''',
          (account_id,digest,stamp())).fetchone()
        if not row:raise ValueError('Verification link is invalid or expired')
        # Test the Fernet key against persisted ciphertext before changing contact state.
        email=decrypt_email(row['email_encrypted'])
        now=stamp()
        db.execute('''UPDATE account_contacts SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL''',
                   (now,account_id))
        cid=uuid4().hex
        db.execute('''INSERT INTO account_contacts(contact_id,account_id,email_encrypted,email_hash,verified_at,created_at)
           VALUES(?,?,?,?,?,?)''',(cid,account_id,encrypt_email(email),row['email_hash'],now,now))
        db.execute('''UPDATE account_email_challenges SET consumed_at=? WHERE challenge_id=?''',
                   (now,row['challenge_id']))
        from .completion_outbox import activate_for_verified_account
        activate_for_verified_account(db,account_id,cid)
        db.commit()
        return {'verified':True,'masked_email':mask_email(email)}
    except Exception:
        db.rollback();raise

def mask_email(addr):
    local,domain=addr.split('@',1)
    return local[:1]+'***@'+domain

def email_status(db,account_id):
    row=db.execute('''SELECT email_encrypted FROM account_contacts WHERE account_id=?
       AND verified_at IS NOT NULL AND revoked_at IS NULL ORDER BY verified_at DESC LIMIT 1''',
       (account_id,)).fetchone()
    if not row:return {'verified':False,'masked_email':None}
    try: return {'verified':True,'masked_email':mask_email(decrypt_email(row['email_encrypted']))}
    except Exception: return {'verified':True,'masked_email':'Encrypted contact on file'}
