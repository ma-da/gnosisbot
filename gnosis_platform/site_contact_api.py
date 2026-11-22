"""Public, size-bounded site contact submission. Explicit opt-in cutover required."""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import closing
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from .auth_api import guard_origin
from .db import connect
from .site_contacts import enabled, submit

router=APIRouter(tags=['site-contact'])

@router.get('/api/v1/contact/status')
def status():
    return JSONResponse({'available':enabled()},headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

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
    if 'application/json' not in request.headers.get('content-type','').lower():
        raise HTTPException(415,'JSON contact submissions required')
    try:
        body=json.loads(payload)
        if not isinstance(body,dict):raise ValueError('Invalid contact request')
        if body.get('website'):
            # Honeypot: no inbox insertion and no signal to spam bots.
            return JSONResponse({'received':True},headers={'Cache-Control':'no-store'})
        with closing(connect()) as db:
            result=submit(db,name=body.get('name'),email=body.get('email'),message=body.get('message'))
    except (ValueError,TypeError,UnicodeDecodeError):
        raise HTTPException(422,'Please check your contact fields')
    except OverflowError:
        raise HTTPException(429,'Too many contact submissions; please try later')
    except (RuntimeError,ImportError,sqlite3.Error) as exc:
        raise HTTPException(503,'Contact storage unavailable') from exc
    return JSONResponse(result,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
