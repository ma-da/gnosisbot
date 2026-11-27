"""Account communications with recipient isolation and opt-in admin-directed replies.

Published notices remain immutable. Replies are allowed ONLY to the notice author's
currently active admin account, never to an arbitrary client-selected destination.
Recipient delete is a per-account soft hide with no destruction of audit data.
"""
from __future__ import annotations

import os
import re
from cryptography.fernet import Fernet
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

ID = re.compile(r'^[0-9a-f]{32}$')
ACCOUNT_ID = re.compile(r'^[0-9a-f]{64}$')
GROUP = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$')


def timestamp(value=None):
    return (value or datetime.now(timezone.utc)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')



def _reply_crypto():
    # Reuse the persistent encryption key already used by protected account contact data.
    # Do not persist user-to-admin replies as plaintext in SQLite or logs.
    key=os.environ.get('GNOSIS_CONTACT_ENCRYPTION_KEY')
    if not key:raise KeyError('Private reply encryption unavailable')
    return Fernet(key.encode('ascii'))


def _encrypt_reply(body):
    return _reply_crypto().encrypt(body.encode('utf-8'))


def _decrypt_reply(blob):
    return _reply_crypto().decrypt(blob).decode('utf-8')

def _clean(value, name, limit, required=False):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be text')
    value = value.strip()
    if (len(value)>limit or (required and not value) or
            any(ord(c)<32 and c not in '\n\t' for c in value)):
        raise ValueError(f'Invalid {name}')
    return value


def _action(label, href):
    label = _clean(label, 'action label', 80)
    href = _clean(href, 'action link', 360)
    if bool(label) != bool(href):
        raise ValueError('Action label and link must both be provided')
    if href:
        parts = urlsplit(href)
        if (not href.startswith('/') or href.startswith('//') or
                parts.scheme or parts.netloc or '\\' in href or
                any(ord(c)<33 for c in href) or
                '\r' in href or '\n' in href or
                not re.fullmatch(r'/[A-Za-z0-9._~!$&\'()*+,;=:@%/?#-]*', href)):
            raise ValueError('Action link must be a safe, same-origin path')
    return label, href


def _audience(db, kind, value):
    if kind not in ('all','group','account'):
        raise ValueError('Invalid audience type')
    value = _clean(value, 'audience', 80)
    if kind == 'all':
        if value: raise ValueError('Everyone cannot have an audience value')
        return ''
    if kind == 'group':
        if not GROUP.fullmatch(value): raise ValueError('Invalid group name')
        if not db.execute('SELECT 1 FROM accounts WHERE account_group=? LIMIT 1',(value,)).fetchone():
            raise ValueError('Group does not currently exist')
        return value
    if not ACCOUNT_ID.fullmatch(value): raise ValueError('Invalid account ID')
    if not db.execute("SELECT 1 FROM accounts WHERE account_id=? AND status='active'",(value,)).fetchone():
        raise ValueError('Target account is not active or does not exist')
    return value


def sanitize(db, data):
    title = _clean(data.get('title',''), 'title', 160, True)
    body = _clean(data.get('body',''), 'body', 4000, True)
    kind = data.get('audience_kind')
    value = _audience(db, kind, data.get('audience_value',''))
    action_label, action_href = _action(data.get('action_label',''),data.get('action_href',''))
    allow_reply=data.get('allow_reply',False)
    if type(allow_reply) is not bool: raise ValueError('Allow-reply option must be boolean')
    return title, body, kind, value, action_label, action_href, int(allow_reply)


def _event(db, notice_id, actor, action, revision, at):
    db.execute('''INSERT INTO gnosis_account_notice_events
        (event_id,notice_id,actor_account_id,action,revision,created_at)
        VALUES(?,?,?,?,?,?)''', (uuid4().hex,notice_id,actor,action,revision,at))


def _find(db, notice_id):
    if not ID.fullmatch(notice_id): raise LookupError('Message not found')
    row = db.execute('SELECT * FROM gnosis_account_notices WHERE notice_id=?',(notice_id,)).fetchone()
    if not row: raise LookupError('Message not found')
    return row


def save_draft(db, *, actor, data, notice_id=None, revision=None):
    if not ACCOUNT_ID.fullmatch(actor): raise ValueError('Invalid author')
    values = sanitize(db,data)
    now=timestamp()
    db.execute('BEGIN IMMEDIATE')
    try:
        if notice_id is None:
            notice_id=uuid4().hex
            db.execute('''INSERT INTO gnosis_account_notices
                (notice_id,title,body,audience_kind,audience_value,action_label,action_href,allow_reply,
                 status,created_by,created_at,updated_at,revision)
                VALUES(?,?,?,?,?,?,?,?,'draft',?,?,?,1)''',(notice_id,*values,actor,now,now))
            _event(db,notice_id,actor,'created',1,now)
        else:
            row=_find(db,notice_id)
            if row['status']!='draft': raise RuntimeError('Only drafts can be edited')
            if type(revision) is not int or revision!=row['revision']:
                raise RuntimeError('Draft changed; reload before saving')
            new_rev=revision+1
            db.execute('''UPDATE gnosis_account_notices SET title=?,body=?,audience_kind=?,audience_value=?,
                    action_label=?,action_href=?,allow_reply=?,updated_at=?,revision=? WHERE notice_id=?''',
                    (*values,now,new_rev,notice_id))
            _event(db,notice_id,actor,'edited',new_rev,now)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(_find(db,notice_id))


def change_status(db, *, actor, notice_id, action, revision):
    if action not in ('published','archived'): raise ValueError('Invalid action')
    now=timestamp()
    db.execute('BEGIN IMMEDIATE')
    try:
        row=_find(db,notice_id)
        if type(revision) is not int or revision!=row['revision']:
            raise RuntimeError('Message changed; reload before continuing')
        if action=='published' and row['status']!='draft':
            raise RuntimeError('Only drafts can be published')
        if action=='archived' and row['status'] not in ('draft','published'):
            raise RuntimeError('Message is already archived')
        next_rev=revision+1
        db.execute('''UPDATE gnosis_account_notices SET status=?,updated_at=?,
           published_at=CASE WHEN ?='published' THEN ? ELSE published_at END,
           revision=? WHERE notice_id=?''',(action,now,action,now,next_rev,notice_id))
        _event(db,notice_id,actor,action,next_rev,now)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(_find(db,notice_id))


def admin_list(db, limit=40, offset=0, include_archived=False):
    if not (1<=limit<=100 and 0<=offset<=100000): raise ValueError('Invalid pagination')
    if type(include_archived) is not bool: raise ValueError('Invalid archive filter')
    where='' if include_archived else "WHERE status!='archived'"
    total=db.execute(f'SELECT COUNT(*) FROM gnosis_account_notices {where}').fetchone()[0]
    items=[dict(x) for x in db.execute(f'''SELECT * FROM gnosis_account_notices
               {where} ORDER BY created_at DESC,notice_id DESC LIMIT ? OFFSET ?''',
               (limit,offset)).fetchall()]
    return {'items':items,'total':total,'limit':limit,'offset':offset}


def groups(db):
    return [x[0] for x in db.execute('''SELECT DISTINCT account_group FROM accounts
              WHERE status='active' AND account_group IS NOT NULL
              ORDER BY account_group COLLATE NOCASE''').fetchall() if x[0]]


def _eligible(row, account_id, account_group):
    return (row['status']=='published' and (row['audience_kind']=='all' or
            (row['audience_kind']=='group' and row['audience_value']==account_group) or
            (row['audience_kind']=='account' and row['audience_value']==account_id)))


def _not_hidden(db, *, account_id, kind, message_id):
    return not db.execute('''SELECT 1 FROM gnosis_account_message_hides
         WHERE account_id=? AND message_kind=? AND message_id=?''',
         (account_id,kind,message_id)).fetchone()


def inbox(db, *, account_id, account_group, limit=12):
    if not ACCOUNT_ID.fullmatch(account_id): raise ValueError('Invalid account')
    if not isinstance(account_group,str): raise ValueError('Invalid group')
    if not 1<=limit<=50: raise ValueError('Invalid inbox size')
    notices=db.execute('''SELECT n.notice_id,n.title,n.body,n.action_label,n.action_href,
              n.published_at,n.created_by,n.allow_reply,
              a.is_admin AS author_is_admin,a.status AS author_status
        FROM gnosis_account_notices n LEFT JOIN accounts a ON a.account_id=n.created_by
        WHERE n.status='published' AND
         (n.audience_kind='all' OR (n.audience_kind='group' AND n.audience_value=?)
           OR (n.audience_kind='account' AND n.audience_value=?))
         AND NOT EXISTS (SELECT 1 FROM gnosis_account_message_hides h
             WHERE h.account_id=? AND h.message_kind='notice' AND h.message_id=n.notice_id)
        ORDER BY n.published_at DESC,n.notice_id DESC LIMIT ?''',
        (account_group,account_id,account_id,limit)).fetchall()
    replies=db.execute('''SELECT r.reply_id,r.notice_id,r.sender_account_id,r.body_ciphertext,r.created_at,
              n.title AS original_title
        FROM gnosis_account_notice_replies r
        JOIN gnosis_account_notices n ON n.notice_id=r.notice_id
        WHERE r.recipient_account_id=?
          AND NOT EXISTS (SELECT 1 FROM gnosis_account_message_hides h
               WHERE h.account_id=? AND h.message_kind='reply' AND h.message_id=r.reply_id)
        ORDER BY r.created_at DESC,r.reply_id DESC LIMIT ?''',
        (account_id,account_id,limit)).fetchall()
    result=[]
    for n in notices:
        label=n['action_label'];href=n['action_href']
        result.append({'message_type':'notice','message_id':n['notice_id'],
             'notice_id':n['notice_id'],'title':n['title'],'body':n['body'],
             'published_at':n['published_at'],
             'action':{'label':label,'href':href} if label and href else None,
             'reply_enabled':bool(n['allow_reply'] and n['author_is_admin']
                   and n['author_status']=='active' and n['created_by']!=account_id)})
    for r in replies:
        result.append({'message_type':'reply','message_id':r['reply_id'],
             'title':'Re: '+r['original_title'],'body':_decrypt_reply(r['body_ciphertext']),
             'from_account':r['sender_account_id'][:12]+'…',
             'published_at':r['created_at'],'action':None,'reply_enabled':False})
    result.sort(key=lambda x:(x['published_at'] or '',x['message_id']),reverse=True)
    return {'schema':'gnosis.account-notices.v1','items':result[:limit]}


def hide_message(db, *, account_id, account_group, kind, message_id):
    if not ACCOUNT_ID.fullmatch(account_id) or not isinstance(account_group,str):
        raise ValueError('Invalid account')
    if kind not in ('notice','reply') or not ID.fullmatch(message_id):
        raise LookupError('Message not found')
    db.execute('BEGIN IMMEDIATE')
    try:
        if kind=='notice':
            row=_find(db,message_id)
            if not _eligible(row,account_id,account_group):
                raise LookupError('Message not found')
        else:
            row=db.execute('''SELECT recipient_account_id FROM gnosis_account_notice_replies
                        WHERE reply_id=?''',(message_id,)).fetchone()
            if not row or row['recipient_account_id']!=account_id:
                raise LookupError('Message not found')
        db.execute('''INSERT OR IGNORE INTO gnosis_account_message_hides
             (account_id,message_kind,message_id,hidden_at) VALUES(?,?,?,?)''',
             (account_id,kind,message_id,timestamp()))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'hidden':True,'message_id':message_id,'message_type':kind}


def send_reply(db, *, sender_id, sender_group, notice_id, body, request_id):
    if not ACCOUNT_ID.fullmatch(sender_id) or not isinstance(sender_group,str):
        raise ValueError('Invalid sender')
    if not ID.fullmatch(notice_id) or not ID.fullmatch(request_id):
        raise ValueError('Invalid reply reference')
    body=_clean(body,'reply',2500,required=True)
    now=timestamp()
    since=timestamp(datetime.now(timezone.utc)-timedelta(hours=24))
    db.execute('BEGIN IMMEDIATE')
    try:
        # Account-bound idempotency: retransmissions of the same reply cannot duplicate it.
        prior=db.execute('''SELECT reply_id,notice_id,body_ciphertext FROM gnosis_account_notice_replies
              WHERE sender_account_id=? AND client_request_id=?''',(sender_id,request_id)).fetchone()
        if prior:
            if prior['notice_id']!=notice_id or _decrypt_reply(prior['body_ciphertext'])!=body:
                raise RuntimeError('Reply request ID reused with different content')
            db.commit()
            return {'sent':True,'reply_id':prior['reply_id']}
        notice=_find(db,notice_id)
        if (not _eligible(notice,sender_id,sender_group) or not notice['allow_reply'] or
              not _not_hidden(db,account_id=sender_id,kind='notice',message_id=notice_id)):
            raise LookupError('Replies are not enabled for this message')
        recipient=notice['created_by']
        if recipient==sender_id: raise ValueError('Cannot reply to your own message')
        # Future allowlist messaging must extend this authorization, not accept destinations from clients.
        admin=db.execute('''SELECT 1 FROM accounts WHERE account_id=?
                 AND status='active' AND is_admin=1''',(recipient,)).fetchone()
        if not admin: raise LookupError('Message author is not an active administrator')
        count=db.execute('''SELECT count(*) FROM gnosis_account_notice_replies
                 WHERE sender_account_id=? AND created_at>=?''',(sender_id,since)).fetchone()[0]
        per_notice=db.execute('''SELECT count(*) FROM gnosis_account_notice_replies
                 WHERE sender_account_id=? AND notice_id=? AND created_at>=?''',
                 (sender_id,notice_id,since)).fetchone()[0]
        if count>=12 or per_notice>=2:
            raise RuntimeError('Reply rate limit reached; try again later')
        reply_id=uuid4().hex
        db.execute('''INSERT INTO gnosis_account_notice_replies
             (reply_id,notice_id,sender_account_id,recipient_account_id,client_request_id,body_ciphertext,created_at)
             VALUES(?,?,?,?,?,?,?)''',(reply_id,notice_id,sender_id,recipient,request_id,_encrypt_reply(body),now))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'sent':True,'reply_id':reply_id}
