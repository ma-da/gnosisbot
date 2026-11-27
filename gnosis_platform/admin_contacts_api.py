"""Administrator-only encrypted contact inbox + optional manual Resend tools.

Outbound emails are claimed/audited BEFORE network I/O and never automatically
retried after a timeout. Incoming Resend reads happen only after user action.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import closing
from datetime import datetime,timedelta,timezone
from urllib.request import Request, urlopen
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .admin_api import require_admin, HEADERS
from .auth_api import guard_origin
from .account_email import canonical, cipher, stamp
from .db import connect
from .site_contacts import enabled, list_messages, change_state
from .ibm_trial_email import submit_resend

router=APIRouter(prefix='/api/v1/admin',dependencies=[Depends(require_admin)],tags=['admin-contacts'])
ID=re.compile(r'^[a-f0-9]{32}$')
SENDERS={'quantum@gnosis.bot','readings@gnosis.bot','support@gnosis.bot'}


def response(value):return JSONResponse(value,headers=HEADERS)

@router.get('/contact-messages')
def get_contacts(offset:int=Query(0,ge=0,le=100000), limit:int=Query(50,ge=1,le=100), quarantine:bool=False):
    if not enabled():return response({'configured':False,'messages':[],'counts':{'total':None,'unread':None},'has_more':False})
    try:
        with closing(connect()) as db: return response({'configured':True,**list_messages(db,offset=offset,limit=limit,quarantine=quarantine)})
    except Exception as exc:
        raise HTTPException(503,'Contact inbox unavailable',headers={'Cache-Control':'no-store'}) from exc

class Action(BaseModel):
    action: str = Field(max_length=32)

@router.post('/contact-messages/{message_id}/state',dependencies=[Depends(guard_origin)])
def update_contact(message_id:str, action:Action, user:dict=Depends(require_admin)):
    if not ID.fullmatch(message_id): raise HTTPException(404,'Message not found')
    if not enabled():raise HTTPException(503,'Contact inbox not configured')
    try:
        with closing(connect()) as db:
            return response(change_state(db,message_id=message_id,actor_account_id=user['account_id'],action=action.action))
    except LookupError:raise HTTPException(404,'Message not found')
    except ValueError:raise HTTPException(400,'Invalid action')

class EmailMessage(BaseModel):
    from_address: str = Field(min_length=4,max_length=100)
    to_address: str = Field(min_length=4,max_length=254)
    subject: str = Field(min_length=1,max_length=200)
    message: str = Field(min_length=1,max_length=10000)
    contact_message_id: str | None = Field(default=None,max_length=32)


def mail_enabled():
    return (os.getenv('GNOSIS_ENABLE_ADMIN_RESEND_SEND')=='YES'
            and bool(os.getenv('RESEND_API_KEY'))
            and bool(os.getenv('GNOSIS_CONTACT_ENCRYPTION_KEY')))

@router.get('/mail/config')
def mail_config():
    return response({'sending_enabled':mail_enabled(),
                     'incoming_enabled':inbound_enabled(),
                     'senders':sorted(SENDERS)})


def perform_send(db, *, actor, body:EmailMessage, transport=None):
    if not mail_enabled():raise RuntimeError('Manual outbound email not configured')
    sender=body.from_address.strip().lower()
    if sender not in SENDERS:raise ValueError('Sender must be an approved gnosis.bot address')
    recipient=canonical(body.to_address)
    subject=body.subject.strip(); content=body.message.strip()
    if (not subject or not content or any(x in subject for x in '\r\n')
            or any(ord(x)<32 and x not in '\n\r\t' for x in content)):
        raise ValueError('Invalid message')
    related=body.contact_message_id
    if related is not None and not ID.fullmatch(related):raise ValueError('Invalid contact reference')
    c=cipher()
    since=stamp(datetime.now(timezone.utc)-timedelta(hours=1))
    mail_id=uuid4().hex
    idem='gnosis-admin-mail-'+mail_id
    db.execute('BEGIN IMMEDIATE')
    try:
        count=db.execute('SELECT count(*) FROM gnosis_admin_manual_emails WHERE actor_account_id=? AND created_at>=?',
                         (actor,since)).fetchone()[0]
        if count>=25:raise OverflowError('Admin send limit reached')
        db.execute('''INSERT INTO gnosis_admin_manual_emails
           (mail_id,actor_account_id,from_address,to_ciphertext,subject_ciphertext,body_ciphertext,
            contact_message_id,status,idempotency_key,created_at)
           VALUES(?,?,?,?,?,?,?,'sending',?,?)''',
           (mail_id,actor,sender,c.encrypt(recipient.encode()),c.encrypt(subject.encode()),
            c.encrypt(content.encode()),related,idem,stamp()))
        db.commit()
    except Exception:
        db.rollback();raise
    try:
        provider_id=submit_resend(api_key=os.environ['RESEND_API_KEY'],
             message={'from':sender,'to':[recipient],'subject':subject,'text':content},
             idem_key=idem,transport=transport)
    except Exception as exc:
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('''UPDATE gnosis_admin_manual_emails SET status='needs_review',
                         completed_at=?,last_error_type=? WHERE mail_id=? AND status='sending' ''',
                       (stamp(),type(exc).__name__,mail_id))
            db.commit()
        except Exception:
            db.rollback();raise
        return {'status':'needs_review','mail_id':mail_id,
                'message':'Provider outcome unknown; do not retry automatically'}
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''UPDATE gnosis_admin_manual_emails SET status='sent',
             provider_message_id=?,completed_at=? WHERE mail_id=? AND status='sending' ''',
             (provider_id,stamp(),mail_id))
        db.commit()
    except Exception:
        db.rollback();raise
    return {'status':'sent','mail_id':mail_id,'provider_message_id':provider_id,
            'message':'Resend accepted the message; delivery is not confirmed'}

@router.post('/mail/send',dependencies=[Depends(guard_origin)])
def send_mail(message:EmailMessage,user:dict=Depends(require_admin)):
    if not mail_enabled():raise HTTPException(503,'Manual email sending not configured')
    try:
        with closing(connect()) as db:
            return response(perform_send(db,actor=user['account_id'],body=message))
    except (ValueError,OverflowError) as exc:
        raise HTTPException(400,str(exc))
    except Exception as exc:
        raise HTTPException(503,'Manual email unavailable; review server configuration') from exc


def inbound_key():
    # A combined send/receive key may be reused; no credentials are ever exposed to the browser.
    return os.getenv('GNOSIS_RESEND_INBOUND_API_KEY') or os.getenv('RESEND_API_KEY')

def inbound_enabled():
    return os.getenv('GNOSIS_ENABLE_RESEND_INCOMING')=='YES' and bool(inbound_key())


def fetch_received(*, email_id=None, limit=30, transport=None):
    if not inbound_enabled():raise RuntimeError('Inbound access disabled')
    if email_id is not None and not re.fullmatch(r'[a-zA-Z0-9-]{8,64}',email_id):
        raise ValueError('Invalid provider message ID')
    url=('https://api.resend.com/emails/receiving/'+email_id if email_id
         else 'https://api.resend.com/emails/receiving?limit='+str(limit))
    req=Request(url,headers={'Authorization':'Bearer '+inbound_key(),
                             'Accept':'application/json','User-Agent':'GnosisBot/1.0'},method='GET')
    with (transport or urlopen)(req,timeout=15) as r:
        # Provider data has a bounded parse size. Never expose raw error bodies.
        raw=r.read(512*1024+1)
        if len(raw)>512*1024:raise RuntimeError('Inbound data too large')
        value=json.loads(raw)
    if email_id:
        items=[value]
    else:
        items=value.get('data',[]) if isinstance(value,dict) else []
        if not isinstance(items,list):raise ValueError('Invalid provider payload')
    safe=[]
    for item in items:
        if not isinstance(item,dict):continue
        tos=item.get('to') or []
        if not isinstance(tos,list) or not any(isinstance(to,str) and to.lower().endswith('@gnosis.bot') for to in tos):continue
        entry={k:item.get(k) for k in ('id','from','subject','created_at')}
        entry['to']=tos[:6]
        if email_id:
            # Plain text ONLY. HTML and attachments are never sent into the DOM.
            entry['text']=(item.get('text') or '')[:20000]
            entry['text_available']=bool(item.get('text'))
        safe.append(entry)
    return {'messages':safe,'has_more':bool(value.get('has_more')) if not email_id else False}

@router.get('/mail/incoming')
def incoming_list(limit:int=Query(30,ge=1,le=50),include_hidden:bool=False):
    if not inbound_enabled():return response({'configured':False,'messages':[]})
    try:
        provider=fetch_received(limit=limit)
        with closing(connect()) as db:
            hidden={r[0] for r in db.execute('SELECT provider_email_id FROM gnosis_admin_received_mail_hidden')}
        msgs=[]
        for m in provider['messages']:
            is_hidden=m.get('id') in hidden
            if is_hidden and not include_hidden:continue
            msgs.append({**m,'hidden':is_hidden})
        return response({'configured':True,'messages':msgs,'has_more':provider['has_more'],
                         'hidden_in_provider_page':sum(1 for m in provider['messages'] if m.get('id') in hidden)})
    except Exception as exc:raise HTTPException(503,'Unable to list incoming email; check Resend receiving permissions') from exc

@router.get('/mail/incoming/{email_id}')
def incoming_read(email_id:str):
    if not inbound_enabled():raise HTTPException(503,'Inbound access not configured')
    try:return response(fetch_received(email_id=email_id))
    except ValueError:raise HTTPException(400,'Invalid message ID')
    except Exception as exc:raise HTTPException(503,'Unable to retrieve incoming email') from exc

class MailVisibility(BaseModel):
    action: str = Field(max_length=16)

@router.post('/mail/incoming/{email_id}/visibility',dependencies=[Depends(guard_origin)])
def set_mail_visibility(email_id:str, change:MailVisibility, user:dict=Depends(require_admin)):
    # This is a Gnosis inbox preference only, NOT a Resend provider deletion.
    if not re.fullmatch(r'[a-zA-Z0-9-]{8,64}',email_id):
        raise HTTPException(400,'Invalid provider email ID')
    if change.action not in ('hide','restore'):
        raise HTTPException(400,'Invalid visibility action')
    if not inbound_enabled():raise HTTPException(503,'Incoming mail not configured')
    try:
        with closing(connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if change.action=='hide':
                    cur=db.execute('''INSERT OR IGNORE INTO gnosis_admin_received_mail_hidden
                        (provider_email_id,hidden_at,actor_account_id) VALUES(?,?,?)''',
                        (email_id,stamp(),user['account_id']))
                else:
                    cur=db.execute('DELETE FROM gnosis_admin_received_mail_hidden WHERE provider_email_id=?',(email_id,))
                if cur.rowcount:
                    db.execute('''INSERT INTO gnosis_admin_received_mail_audit
                        (audit_id,provider_email_id,actor_account_id,action,created_at)
                        VALUES(?,?,?,?,?)''',(uuid4().hex,email_id,user['account_id'],change.action,stamp()))
                db.commit()
            except Exception:
                db.rollback();raise
        return response({'changed':bool(cur.rowcount),'hidden':change.action=='hide'})
    except Exception as exc:
        raise HTTPException(503,'Unable to update incoming email visibility') from exc
