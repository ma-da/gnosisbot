"""First-party contact submission, bounded before parsing."""
from __future__ import annotations
import json, sqlite3
from html import escape
from urllib.parse import parse_qs
from contextlib import closing
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.concurrency import run_in_threadpool
from .auth_api import guard_origin
from .db import connect
from .site_contacts import enabled, submit
from .contact_protection import BODY_LIMIT, AdmissionError, issue, record, prune

router=APIRouter(tags=['site-contact'])
HEADERS={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}
HTML_HEADERS={**HEADERS,'Content-Security-Policy':"default-src 'none'; style-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"}

@router.get('/api/v1/contact/status')
def status():
    return JSONResponse({'available':enabled()},headers=HEADERS)

@router.post('/api/v1/contact/token',dependencies=[Depends(guard_origin)])
def token():
    if not enabled(): raise HTTPException(503,'Contact unavailable',headers=HEADERS)
    try:return JSONResponse(issue(),headers=HEADERS)
    except (RuntimeError,ValueError):raise HTTPException(503,'Contact unavailable',headers=HEADERS)

MESSAGES={'too_early':'Please wait before sending.','token_invalid':'Open a new contact form and try again.',
 'token_expired':'The form expired. Please try again.','token_used':'This form has already been used. Check whether your message was received before sending again.',
 'rate_limited':'Too many contact submissions. Please try later.','invalid_fields':'Please check your contact fields.',
 'too_large':'Message too large. Please shorten it.','unsupported_type':'Use a standard contact form.', 'unavailable':'Contact temporarily unavailable.'}

def html_form(ticket, message='', values=None, status=200):
    v=values or {}; esc=lambda name:escape(v.get(name,'') if isinstance(v.get(name,''),str) else '',quote=True)
    token_value=escape(ticket['token'],quote=True)
    html=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Contact | Gnosis.bot</title><link rel="stylesheet" href="/assets/css/style.css"><main class="home-section home-contact">
    <h1>Send a message</h1><p>Wait at least {ticket['minimum_seconds']} seconds after opening this form before sending.</p><p role="status">{escape(message)}</p>
    <form class="contact-form" action="/api/v1/contact" method="post">
    <label class="contact-field">Name<input name="name" maxlength="120" required value="{esc('name')}"></label>
    <label class="contact-field">Email<input type="email" name="email" maxlength="254" required value="{esc('email')}"></label>
    <label class="contact-field contact-field--message">Message<textarea name="message" maxlength="4000" required>{esc('message')}</textarea></label>
    <input type="hidden" name="token" value="{token_value}"><input name="website" hidden tabindex="-1" autocomplete="off" aria-hidden="true">
    <button class="contact-submit" type="submit">SEND MESSAGE</button></form><p><a href="/#contact">Return to Gnosis.bot</a></p></main></html>'''
    return HTMLResponse(html,status_code=status,headers=HTML_HEADERS)

@router.get('/api/v1/contact/form')
def fallback_form():
    if not enabled():raise HTTPException(503,'Contact unavailable',headers=HEADERS)
    try:return html_form(issue())
    except (RuntimeError,ValueError):raise HTTPException(503,'Contact unavailable',headers=HEADERS)

def received_form():
    return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><title>Message received | Gnosis.bot</title><main><h1>Message received</h1><p>Thank you.</p><a href="/#contact">Return to Gnosis.bot</a></main></html>',headers=HTML_HEADERS)

def failure(code,status,from_form=False,body=None,wait=None):
    msg=MESSAGES[code]
    if wait:msg+=f' Try again in {wait} seconds.'
    if from_form and status in (403,425,422):
        # Preserve typed fields safely; a too-early token keeps its original issuance time.
        try:
            ticket=issue()
            if status==425 and body:ticket['token']=body['token']
            return html_form(ticket,msg,body,status)
        except (RuntimeError,ValueError):pass
    if from_form:
        return HTMLResponse(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Contact | Gnosis.bot</title><p>{escape(msg)}</p><p><a href="/api/v1/contact/form">Open contact form</a></p></html>',status_code=status,headers=HTML_HEADERS)
    return JSONResponse({'detail':msg,'code':code,**({'retry_after':wait} if wait else {})},status_code=status,headers={**HEADERS,**({'Retry-After':str(wait)} if wait else {})})

def count_failure(outcome):
    # Counters never contain request data; best effort if storage is unavailable.
    try:
        with closing(connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:record(db,outcome);db.commit()
            except Exception:db.rollback();raise
    except sqlite3.Error:pass

def unique_pairs(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('Duplicate field')
        result[k]=v
    return result

def admit(body):
    with closing(connect()) as db:
        return submit(db,name=body.get('name'),email=body.get('email'),message=body.get('message'),token=body.get('token'),website=body.get('website',''))

@router.post('/api/v1/contact',dependencies=[Depends(guard_origin)])
async def receive(request:Request):
    if not enabled():return failure('unavailable',503)
    content_type=request.headers.get('content-type','').split(';',1)[0].strip().lower()
    from_form=content_type=='application/x-www-form-urlencoded'
    async def reject(code,status,body=None,wait=None):
        await run_in_threadpool(count_failure,'rate_limited' if status==429 else 'rejected')
        return failure(code,status,from_form,body,wait)
    if not from_form and content_type!='application/json':return await reject('unsupported_type',415)
    size=request.headers.get('content-length')
    if size is not None:
        try:
            if int(size)<0:raise ValueError()
            if int(size)>BODY_LIMIT:return await reject('too_large',413)
        except ValueError:return await reject('invalid_fields',422)
    payload=bytearray()
    async for chunk in request.stream():
        if len(chunk)>BODY_LIMIT-len(payload):return await reject('too_large',413)
        payload.extend(chunk)
    body=None
    try:
        if from_form:
            fields=parse_qs(payload.decode('utf-8'),keep_blank_values=True,max_num_fields=5,errors='strict')
            if any(len(v)!=1 for v in fields.values()):raise ValueError('Duplicate field')
            body={k:v[0] for k,v in fields.items()}
        else:body=json.loads(payload,object_pairs_hook=unique_pairs)
        if not isinstance(body,dict) or set(body)-{'name','email','message','website','token'} or not all(isinstance(v,str) for v in body.values()):
            raise ValueError('Invalid fields')
        result=await run_in_threadpool(admit,body)
    except AdmissionError as exc:return await reject(exc.code,exc.status,body,exc.wait)
    except (ValueError,TypeError,UnicodeError,RecursionError):return await reject('invalid_fields',422,body if isinstance(body,dict) else None)
    except (RuntimeError,ImportError,sqlite3.Error):return failure('unavailable',503,from_form)
    return received_form() if from_form else JSONResponse(result,headers=HEADERS)
