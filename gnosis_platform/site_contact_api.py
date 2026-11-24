"""Public, size-bounded site contact submission. Explicit opt-in cutover required."""
from __future__ import annotations
import json
import os
import sqlite3
from urllib.parse import parse_qs
from contextlib import closing
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from .auth_api import guard_origin
from .db import connect
from .site_contacts import enabled, submit

router=APIRouter(tags=['site-contact'])

@router.get('/api/v1/contact/status')
def status():
    return JSONResponse({'available':enabled()},headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

def form_result(ok:bool,status:int=200):
    # No-JavaScript HTML fallback; never reflect visitor-supplied content.
    title='Message received' if ok else 'Message not sent'
    message=('Thank you. Your message has been received.' if ok else
             'We could not accept your message. Check the fields or try again later.')
    html=('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
          'content="width=device-width,initial-scale=1"><title>'+title+' | Gnosis.bot</title>'
          '<main><h1>'+title+'</h1><p>'+message+'</p>'
          '<p><a href="/#contact">Return to Gnosis.bot</a></p></main></html>')
    return HTMLResponse(html,status_code=status,headers={'Cache-Control':'no-store',
          'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; style-src 'none'; base-uri 'none'; form-action 'none'"})

@router.post('/api/v1/contact',dependencies=[Depends(guard_origin)])
async def receive(request:Request):
    if not enabled():
        raise HTTPException(503,'Native contact form not yet enabled')
    # Bounded streaming prevents giant request bodies from exhausting RAM.
    payload=bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload)>12000:
            raise HTTPException(413,'Message too large')
    content_type=request.headers.get('content-type','').lower()
    from_form='application/x-www-form-urlencoded' in content_type
    if not from_form and 'application/json' not in content_type:
        raise HTTPException(415,'JSON or standard form submissions required')
    try:
        if from_form:
            fields=parse_qs(payload.decode('utf-8'),keep_blank_values=True,
                            strict_parsing=False,max_num_fields=10)
            if any(len(v)!=1 for v in fields.values()):raise ValueError('Duplicate contact field')
            body={k:v[0] for k,v in fields.items()}
        else:
            body=json.loads(payload)
        if not isinstance(body,dict):raise ValueError('Invalid contact request')
        if body.get('website'):
            # Honeypot: no inbox insertion and no signal to spam bots.
            return form_result(True) if from_form else JSONResponse({'received':True},headers={'Cache-Control':'no-store'})
        with closing(connect()) as db:
            result=submit(db,name=body.get('name'),email=body.get('email'),message=body.get('message'))
    except (ValueError,TypeError,UnicodeDecodeError):
        if from_form:return form_result(False,422)
        raise HTTPException(422,'Please check your contact fields')
    except OverflowError:
        if from_form:return form_result(False,429)
        raise HTTPException(429,'Too many contact submissions; please try later')
    except (RuntimeError,ImportError,sqlite3.Error) as exc:
        if from_form:return form_result(False,503)
        raise HTTPException(503,'Contact storage unavailable') from exc
    if from_form:return form_result(True)
    return JSONResponse(result,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
