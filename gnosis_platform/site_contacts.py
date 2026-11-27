"""Encrypted site contact inbox. No PII is sent to admin overview or logs.

Only the verified admin endpoint can decrypt stored messages. Reuses the existing
long-lived GNOSIS_CONTACT_ENCRYPTION_KEY; losing it loses the ability to read mail.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from .account_email import canonical, cipher, email_hash, stamp

MAX_NAME = 120
MAX_MESSAGE = 4000

from .contact_protection import (AdmissionError, now_ms, verify, policy, record, prune, statistics, quarantine_reason)


def enabled():
    return os.getenv('GNOSIS_ENABLE_NATIVE_CONTACTS') == '1' and bool(os.getenv('GNOSIS_CONTACT_ENCRYPTION_KEY'))


def validated(name, email, message):
    if not all(isinstance(v,str) for v in (name,email,message)):
        raise ValueError('Invalid contact fields')
    name = name.strip()
    message = message.strip()
    if not 1 <= len(name) <= MAX_NAME or not 1 <= len(message) <= MAX_MESSAGE:
        raise ValueError('Please provide your name and a message within the supported size limits')
    if any(ord(c)<32 and c not in '\n\r\t' for c in name+message):
        raise ValueError('Invalid control characters')
    return name, canonical(email), message


def submit(db, *, name, email, message, token=None, website=''):
    now=now_ms()
    db.execute('BEGIN IMMEDIATE')
    try:
        nonce,expires=verify(token,now)
        if db.execute('SELECT 1 FROM gnosis_contact_consumed_tokens WHERE token_id=?',(nonce,)).fetchone():
            raise AdmissionError(409,'token_used')
        if website:
            # Reject without reserving storage or disclosing the honeypot.
            record(db,'rejected',now)
            db.commit()
            return {'received':True}
        name,email,message=validated(name,email,message)
        key=cipher()
        digest=email_hash(email)
        _,_,per_email,global_limit,_=policy()
        prune(db,now)
        same=db.execute('SELECT count(*) FROM gnosis_contact_consumed_tokens WHERE email_digest=? AND accepted_ms>?',(digest,now-86400000)).fetchone()[0]
        total=db.execute('SELECT count(*) FROM gnosis_contact_consumed_tokens WHERE accepted_ms>?',(now-3600000,)).fetchone()[0]
        if same>=per_email or total>=global_limit:
            raise AdmissionError(429,'rate_limited')
        reason=quarantine_reason(message)
        db.execute('INSERT INTO gnosis_contact_consumed_tokens VALUES(?,?,?,?)',(nonce,digest,now,expires))
        db.execute('''INSERT INTO gnosis_site_contact_messages
          (message_id,name_ciphertext,email_ciphertext,email_digest,message_ciphertext,source,created_at,quarantine_reason)
          VALUES(?,?,?,?,?,'homepage',?,?)''',
          (uuid4().hex,key.encrypt(name.encode('utf8')),key.encrypt(email.encode('utf8')),digest,
           key.encrypt(message.encode('utf8')),stamp(),reason))
        record(db,'quarantined' if reason else 'accepted',now)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'received': True}


def counts(db):
    values=db.execute('''SELECT count(*) AS n, SUM(CASE WHEN read_at IS NULL AND archived_at IS NULL THEN 1 ELSE 0 END) AS unread
       FROM gnosis_site_contact_messages WHERE deleted_at IS NULL AND quarantine_reason IS NULL''').fetchone()
    return {'total':values['n'],'unread':values['unread'] or 0, 'quarantine':db.execute('SELECT count(*) FROM gnosis_site_contact_messages WHERE deleted_at IS NULL AND quarantine_reason IS NOT NULL').fetchone()[0]}


def list_messages(db, *, offset=0, limit=50, quarantine=False):
    db.execute('BEGIN IMMEDIATE')
    try:
        prune(db)
        db.commit()
    except Exception:
        db.rollback();raise
    key=cipher()
    condition='quarantine_reason IS NOT NULL' if quarantine else 'quarantine_reason IS NULL' 
    rows=db.execute(f'''SELECT * FROM gnosis_site_contact_messages
      WHERE deleted_at IS NULL AND {condition}
      ORDER BY (CASE WHEN archived_at IS NULL AND read_at IS NULL THEN 0
                     WHEN archived_at IS NULL THEN 1 ELSE 2 END), created_at DESC, message_id DESC
      LIMIT ? OFFSET ?''',(limit,offset)).fetchall()
    result=[]
    for r in rows:
        result.append({
            'id':r['message_id'],
            'name':key.decrypt(r['name_ciphertext']).decode('utf8'),
            'email':key.decrypt(r['email_ciphertext']).decode('utf8'),
            'message':key.decrypt(r['message_ciphertext']).decode('utf8'),
            'created_at':r['created_at'], 'read_at':r['read_at'], 'archived_at':r['archived_at'], 'quarantine_reason':r['quarantine_reason']
        })
    return {'counts':counts(db),'messages':result,'offset':offset,'limit':limit,
            'spam':statistics(db), 'has_more': db.execute(f'SELECT count(*) FROM gnosis_site_contact_messages WHERE deleted_at IS NULL AND {condition}').fetchone()[0] > offset+len(rows)}


def change_state(db, *, message_id, actor_account_id, action):
    if action not in ('mark_read','mark_unread','archive','restore','delete','release'):
        raise ValueError('Unknown action')
    now=stamp()
    db.execute('BEGIN IMMEDIATE')
    try:
        before=db.execute('SELECT read_at, archived_at, deleted_at, quarantine_reason FROM gnosis_site_contact_messages WHERE message_id=?',(message_id,)).fetchone()
        if before is None or before['deleted_at'] is not None: raise LookupError('Message missing')
        if before['quarantine_reason'] is not None and action not in ('release','delete'):
            raise ValueError('Release quarantined message first')
        if action=='release':
            if before['quarantine_reason'] is None: raise ValueError('Message not quarantined')
            # Refuse release after retention even if the admin page was left open.
            from .contact_protection import policy
            cutoff=stamp(datetime.now(timezone.utc)-timedelta(days=policy()[4]))
            updated=db.execute("UPDATE gnosis_site_contact_messages SET quarantine_reason=NULL,read_at=NULL,archived_at=NULL WHERE message_id=? AND created_at>?",(message_id,cutoff))
            if not updated.rowcount: raise LookupError('Message expired')
            db.execute('INSERT INTO gnosis_contact_quarantine_releases VALUES(?,?,?)',(message_id,actor_account_id,now))
            db.commit()
            return {'changed':True,'counts':counts(db)}
        if action=='delete':
            # Erase the locally stored encrypted personal fields; preserve only a
            # pseudonymous row ID so existing audit and outbound FK links remain valid.
            updated=db.execute('''UPDATE gnosis_site_contact_messages
               SET name_ciphertext=X'', email_ciphertext=X'', message_ciphertext=X'',
                   email_digest=lower(hex(randomblob(32))), quarantine_reason=NULL, deleted_at=?,
                   read_at=COALESCE(read_at,?), archived_at=COALESCE(archived_at,?)
               WHERE message_id=? AND deleted_at IS NULL''',(now,now,now,message_id))
            if updated.rowcount:
                db.execute('''INSERT INTO gnosis_admin_site_contact_deletions
                   (message_id,actor_account_id,deleted_at) VALUES(?,?,?)''',
                   (message_id,actor_account_id,now))
            db.commit()
            return {'changed':bool(updated.rowcount),'counts':counts(db)}
        if action=='mark_read':
            updated=db.execute('UPDATE gnosis_site_contact_messages SET read_at=? WHERE message_id=? AND read_at IS NULL',(now,message_id))
        elif action=='mark_unread':
            updated=db.execute('UPDATE gnosis_site_contact_messages SET read_at=NULL WHERE message_id=? AND read_at IS NOT NULL',(message_id,))
        elif action=='archive':
            updated=db.execute('UPDATE gnosis_site_contact_messages SET archived_at=? WHERE message_id=? AND archived_at IS NULL',(now,message_id))
        else:
            updated=db.execute('UPDATE gnosis_site_contact_messages SET archived_at=NULL WHERE message_id=? AND archived_at IS NOT NULL',(message_id,))
        if updated.rowcount:
            db.execute('INSERT INTO gnosis_admin_contact_audit(audit_id,message_id,actor_account_id,action,created_at) VALUES(?,?,?,?,?)',
                       (uuid4().hex,message_id,actor_account_id,action,now))
        db.commit()
    except Exception:
        db.rollback();raise
    return {'changed':bool(updated.rowcount),'counts':counts(db)}
