"""Encrypted media CRM. No email sends, redeemable codes, or credit ledger writes.

Low-volume records are decrypted for admin-side searching only. Full contact data
and activity detail stay encrypted at rest with the existing contact Fernet key.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from uuid import uuid4
from .account_email import cipher, canonical

STATUSES = ('researching','ready','contacted','follow_up','responded','published','declined','archived')
ACTIVITIES = ('note','contacted','reply','coverage','follow_up')
ID = re.compile(r'^[0-9a-f]{32}$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
PUBLIC_FIELDS = ('name','outlet','email','role','topics','notes','published_url')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def sanitize(body):
    """Prepare data for encrypted storage; reject malformed or oversized input."""
    from urllib.parse import urlsplit
    limits = {'name':160,'outlet':160,'email':254,'role':160,'topics':500,'notes':5000,'published_url':800}
    data = {}
    for key,maxlen in limits.items():
        val = body.get(key,'')
        if not isinstance(val,str): raise ValueError(f'{key} must be text')
        val=val.strip()
        if len(val)>maxlen or '\x00' in val:raise ValueError(f'{key} exceeds its allowed length')
        data[key]=val
    if not (data['name'] or data['outlet']):raise ValueError('Name or outlet required')
    if data['email']:data['email']=canonical(data['email'])
    if data['published_url']:
        u=urlsplit(data['published_url'])
        if (u.scheme!='https' or not u.hostname or u.username or u.password
                or any(ord(x)<33 for x in data['published_url']) or '\\' in data['published_url']):
            raise ValueError('Publication URL must be HTTPS')
    status=body.get('status','researching')
    if status not in STATUSES:raise ValueError('Invalid outreach status')
    follow=body.get('next_followup') or None
    if follow is not None:
        if not isinstance(follow,str) or not DATE.fullmatch(follow):raise ValueError('Invalid follow-up date')
        try:datetime.strptime(follow,'%Y-%m-%d')
        except ValueError as e:raise ValueError('Invalid follow-up date') from e
    given=body.get('claim_code_given',False)
    if type(given) is not bool:raise ValueError('Claim-code flag must be boolean')
    return data,status,follow,given


def encrypt(obj):return cipher().encrypt(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8'))
def decrypt(blob):return json.loads(cipher().decrypt(blob).decode('utf-8'))


def _public(row):
    data=decrypt(row['details_ciphertext'])
    return {**data,'id':row['contact_id'],'status':row['status'],
            'next_followup':row['next_followup'],
            'claim_code_given':bool(row['claim_code_given']),
            'claim_code_given_at':row['claim_code_given_at'],
            'created_at':row['created_at'],'updated_at':row['updated_at'],
            'revision':row['revision']}


def get(db,contact_id):
    if not ID.fullmatch(contact_id):raise LookupError('Contact not found')
    row=db.execute('SELECT * FROM gnosis_media_contacts WHERE contact_id=?',(contact_id,)).fetchone()
    if row is None:raise LookupError('Contact not found')
    return _public(row)


def list_contacts(db,*,query='',status='',limit=60,offset=0):
    if not isinstance(query,str) or len(query)>160:raise ValueError('Search too long')
    if status and status not in STATUSES:raise ValueError('Invalid status filter')
    if not (1<=limit<=100 and 0<=offset<=100000):raise ValueError('Invalid pagination')
    rows=db.execute('SELECT * FROM gnosis_media_contacts ORDER BY updated_at DESC,contact_id DESC').fetchall()
    needle=query.casefold().strip()
    out=[]
    for row in rows:
        if status and row['status']!=status:continue
        item=_public(row)
        if needle and not any(needle in item[f].casefold() for f in ('name','outlet','email','role','topics','notes')):continue
        out.append(item)
    return {'contacts':out[offset:offset+limit], 'total':len(out), 'has_more':offset+limit<len(out)}


def _audit(db,*,contact_id,actor,kind,details,now):
    db.execute('''INSERT INTO gnosis_media_activity
       (activity_id,contact_id,actor_account_id,kind,details_ciphertext,created_at)
       VALUES(?,?,?,?,?,?)''',(uuid4().hex,contact_id,actor,kind,encrypt(details),now))


def save(db,*,body,actor,contact_id=None,expected_revision=None):
    data,status,follow,given=sanitize(body)
    now=stamp()
    db.execute('BEGIN IMMEDIATE')
    try:
        if contact_id is None:
            contact_id=uuid4().hex
            db.execute('''INSERT INTO gnosis_media_contacts
              (contact_id,details_ciphertext,status,next_followup,claim_code_given,
               claim_code_given_at,revision,created_at,updated_at)
              VALUES(?,?,?,?,?,?,1,?,?)''',
              (contact_id,encrypt(data),status,follow,int(given),now if given else None,now,now))
            _audit(db,contact_id=contact_id,actor=actor,kind='created',details={'after':{**data,'status':status,'next_followup':follow,'claim_code_given':given}},now=now)
        else:
            if not ID.fullmatch(contact_id):raise LookupError('Contact not found')
            oldrow=db.execute('SELECT * FROM gnosis_media_contacts WHERE contact_id=?',(contact_id,)).fetchone()
            if oldrow is None:raise LookupError('Contact not found')
            if type(expected_revision) is not int or expected_revision!=oldrow['revision']:
                raise RuntimeError('Contact changed; reload it before saving')
            before=_public(oldrow)
            if before['claim_code_given'] == given:
                code_at=oldrow['claim_code_given_at']
            else:
                code_at=now if given else None
            db.execute('''UPDATE gnosis_media_contacts SET details_ciphertext=?,status=?,
                next_followup=?,claim_code_given=?,claim_code_given_at=?,
                revision=revision+1,updated_at=? WHERE contact_id=?''',
                (encrypt(data),status,follow,int(given),code_at,now,contact_id))
            after={**data,'status':status,'next_followup':follow,'claim_code_given':given}
            prior={k:before[k] for k in after}
            changed={k:{'before':prior[k],'after':after[k]} for k in after if prior[k]!=after[k]}
            if changed:_audit(db,contact_id=contact_id,actor=actor,kind='updated',details={'changed':changed},now=now)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get(db,contact_id)


def add_activity(db,*,contact_id,actor,kind,note):
    if not ID.fullmatch(contact_id):raise LookupError('Contact not found')
    if kind not in ACTIVITIES:raise ValueError('Invalid activity type')
    if not isinstance(note,str) or not (1<=len(note.strip())<=2000) or '\x00' in note:
        raise ValueError('Activity note must be 1–2000 characters')
    now=stamp()
    db.execute('BEGIN IMMEDIATE')
    try:
        existing=db.execute('SELECT 1 FROM gnosis_media_contacts WHERE contact_id=?',(contact_id,)).fetchone()
        if not existing:raise LookupError('Contact not found')
        _audit(db,contact_id=contact_id,actor=actor,kind=kind,details={'note':note.strip()},now=now)
        db.commit()
    except Exception:db.rollback();raise
    return {'recorded':True}


def history(db,contact_id,limit=100):
    if not ID.fullmatch(contact_id):raise LookupError('Contact not found')
    if not (1<=limit<=200):raise ValueError('Invalid history limit')
    if not db.execute('SELECT 1 FROM gnosis_media_contacts WHERE contact_id=?',(contact_id,)).fetchone():
        raise LookupError('Contact not found')
    rows=db.execute('SELECT * FROM gnosis_media_activity WHERE contact_id=? ORDER BY created_at DESC,activity_id DESC LIMIT ?', (contact_id,limit)).fetchall()
    return [{'kind':r['kind'],'created_at':r['created_at'],
             'actor_account_id':r['actor_account_id'],'details':decrypt(r['details_ciphertext'])} for r in rows]
