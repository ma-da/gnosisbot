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
MAX_MESSAGE = 5000


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


def submit(db, *, name, email, message):
    name,email,message = validated(name,email,message)
    key = cipher()  # Fail closed BEFORE trying to insert anything.
    digest = email_hash(email)
    now = stamp()
    cutoff_sender = stamp(datetime.now(timezone.utc)-timedelta(hours=1))
    cutoff_global = stamp(datetime.now(timezone.utc)-timedelta(minutes=10))
    db.execute('BEGIN IMMEDIATE')
    try:
        same = db.execute('SELECT count(*) FROM gnosis_site_contact_messages WHERE email_digest=? AND created_at>=?',(digest,cutoff_sender)).fetchone()[0]
        total = db.execute('SELECT count(*) FROM gnosis_site_contact_messages WHERE created_at>=?',(cutoff_global,)).fetchone()[0]
        if same >= 4 or total >= 60:
            raise OverflowError('Contact submission rate exceeded')
        db.execute('''INSERT INTO gnosis_site_contact_messages
          (message_id,name_ciphertext,email_ciphertext,email_digest,message_ciphertext,source,created_at)
          VALUES(?,?,?,?,?,'homepage',?)''',
          (uuid4().hex,key.encrypt(name.encode('utf8')),key.encrypt(email.encode('utf8')),digest,
           key.encrypt(message.encode('utf8')),now))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'received': True}


def counts(db):
    values=db.execute('''SELECT count(*) AS n, SUM(CASE WHEN read_at IS NULL AND archived_at IS NULL THEN 1 ELSE 0 END) AS unread
       FROM gnosis_site_contact_messages WHERE deleted_at IS NULL''').fetchone()
    return {'total':values['n'],'unread':values['unread'] or 0}


def list_messages(db, *, offset=0, limit=50):
    key=cipher()
    rows=db.execute('''SELECT * FROM gnosis_site_contact_messages
      WHERE deleted_at IS NULL
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
            'created_at':r['created_at'], 'read_at':r['read_at'], 'archived_at':r['archived_at']
        })
    return {'counts':counts(db),'messages':result,'offset':offset,'limit':limit,
            'has_more': db.execute('SELECT count(*) FROM gnosis_site_contact_messages WHERE deleted_at IS NULL').fetchone()[0] > offset+len(rows)}


def change_state(db, *, message_id, actor_account_id, action):
    if action not in ('mark_read','mark_unread','archive','restore','delete'):
        raise ValueError('Unknown action')
    now=stamp()
    db.execute('BEGIN IMMEDIATE')
    try:
        before=db.execute('SELECT read_at, archived_at, deleted_at FROM gnosis_site_contact_messages WHERE message_id=?',(message_id,)).fetchone()
        if before is None or before['deleted_at'] is not None: raise LookupError('Message missing')
        if action=='delete':
            # Erase the locally stored encrypted personal fields; preserve only a
            # pseudonymous row ID so existing audit and outbound FK links remain valid.
            updated=db.execute('''UPDATE gnosis_site_contact_messages
               SET name_ciphertext=X'', email_ciphertext=X'', message_ciphertext=X'',
                   email_digest=lower(hex(randomblob(32))), deleted_at=?,
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
