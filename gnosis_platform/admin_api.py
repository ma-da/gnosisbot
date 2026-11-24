"""Opt-in, administrator-authorized operations dashboard; no paid actions."""
import os, threading
from pathlib import Path
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from .auth_api import authenticated,guard_origin
from .db import connect
from .config import get_settings
from .admin_metrics import overview
from .admin_btc import check

HEADERS={'Cache-Control':'no-store, private','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}

def require_admin(user:dict=Depends(authenticated)):
    if os.getenv('GNOSIS_ENABLE_ADMIN_DASHBOARD')!='1' or user.get('is_admin')!=1:
        raise HTTPException(403,'Administrator access required',headers={'Cache-Control':'no-store'})
    return user

router=APIRouter(dependencies=[Depends(require_admin)],tags=['admin-dashboard'])
ui=Path(__file__).resolve().parent/'admin_ui'
lock=threading.Lock()

@router.get('/admin/',include_in_schema=False)
def page():return FileResponse(ui/'index.html',headers=HEADERS)
@router.get('/admin/dashboard.css',include_in_schema=False)
def css():return FileResponse(ui/'dashboard.css',media_type='text/css',headers=HEADERS)
@router.get('/admin/dashboard.js',include_in_schema=False)
def js():return FileResponse(ui/'dashboard.js',media_type='text/javascript',headers=HEADERS)

@router.get('/api/v1/admin/overview')
def get_overview(days:int=Query(30,ge=1,le=365)):
    try:
        with closing(connect()) as db:
            db.execute('BEGIN')
            data=overview(db,days)
            db.rollback()
        return JSONResponse(data,headers=HEADERS)
    except Exception as e:raise HTTPException(503,'Admin metrics unavailable; check database migrations and configuration',headers={'Cache-Control':'no-store'}) from e

@router.post('/api/v1/admin/transparency/{size}/check',dependencies=[Depends(guard_origin)])
def btc_check(size:int):
    if size<0 or size>=2**63:raise HTTPException(404,'Unknown checkpoint')
    if not lock.acquire(blocking=False):raise HTTPException(429,'Another proof check is running')
    try:
        with closing(connect()) as db:
            result=check(db,size,get_settings().data_dir/'transparency'/'public',os.getenv('GNOSIS_OTS_EXECUTABLE',str(Path.home()/'.venvs/opentimestamps/bin/ots')))
        return JSONResponse(result,headers=HEADERS)
    except LookupError as e:raise HTTPException(404,'Unknown checkpoint') from e
    except (ValueError,OSError) as e:raise HTTPException(409,'Checkpoint or proof is missing, changed, or invalid') from e
    finally:lock.release()


# File-backed interpretation editor (same authenticated admin authorization).
@router.get('/admin/interpretations/',include_in_schema=False)
def interpretation_editor_page():
    return FileResponse(ui/'editor.html',headers=HEADERS)

@router.get('/admin/editor.css',include_in_schema=False)
def interpretation_editor_css():
    return FileResponse(ui/'editor.css',media_type='text/css',headers=HEADERS)

@router.get('/admin/editor.js',include_in_schema=False)
def interpretation_editor_js():
    return FileResponse(ui/'editor.js',media_type='text/javascript',headers=HEADERS)

# Contacts UI assets inherit the existing admin authentication and no-store headers.
@router.get('/admin/contacts.js',include_in_schema=False)
def contacts_js():
    return FileResponse(ui/'contacts.js',media_type='text/javascript',headers=HEADERS)

@router.get('/admin/contacts.css',include_in_schema=False)
def contacts_css():
    return FileResponse(ui/'contacts.css',media_type='text/css',headers=HEADERS)

# Media CRM assets inherit per-request admin auth and private security headers.
@router.get('/admin/media.js',include_in_schema=False)
def media_js():
    return FileResponse(ui/'media.js',media_type='text/javascript',headers=HEADERS)

@router.get('/admin/media.css',include_in_schema=False)
def media_css():
    return FileResponse(ui/'media.css',media_type='text/css',headers=HEADERS)

@router.get('/admin/credits.js',include_in_schema=False)
def credits_js():
    return FileResponse(ui/'credits.js',media_type='text/javascript',headers=HEADERS)

@router.get('/admin/credits.css',include_in_schema=False)
def credits_css():
    return FileResponse(ui/'credits.css',media_type='text/css',headers=HEADERS)

# All finance assets require per-request administrator authentication.
@router.get('/admin/finance.js',include_in_schema=False)
def financials_js():
    return FileResponse(ui/'finance.js',media_type='text/javascript',headers=HEADERS)

@router.get('/admin/finance.css',include_in_schema=False)
def financials_css():
    return FileResponse(ui/'finance.css',media_type='text/css',headers=HEADERS)
