"""Authenticated account notices, scoped replies and administrator-only management.

No outbound mail, cross-account direct messaging, payments, or credit operations.
"""
from __future__ import annotations
from pathlib import Path
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from .auth_api import authenticated, guard_origin
from .admin_api import require_admin, HEADERS
from .db import connect
from . import account_communications as store

account_router = APIRouter(prefix='/api/v1/accounts', tags=['account-communications'])
admin_router = APIRouter(dependencies=[Depends(require_admin)], tags=['admin-communications'])
_UI = Path(__file__).resolve().parent/'admin_ui'


class DraftBody(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)
    audience_kind: str = Field(pattern=r'^(all|group|account)$')
    audience_value: str = Field(default='', max_length=80)
    action_label: str = Field(default='', max_length=80)
    action_href: str = Field(default='', max_length=360)
    allow_reply: bool = False
    revision: int | None = Field(default=None, ge=1)


class StatusBody(BaseModel):
    revision: int = Field(ge=1)


class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=2500)
    client_request_id: str = Field(pattern=r'^[0-9a-f]{32}$')


class HideBody(BaseModel):
    message_type: str = Field(pattern=r'^(notice|reply)$')


def _admin_call(operation, *args, **kwargs):
    try:
        with closing(connect()) as db:
            result=operation(db,*args,**kwargs)
        return JSONResponse(result,headers=HEADERS)
    except LookupError as e:
        raise HTTPException(404,'Message not found',headers={'Cache-Control':'no-store'}) from e
    except ValueError as e:
        raise HTTPException(422,str(e),headers={'Cache-Control':'no-store'}) from e
    except RuntimeError as e:
        raise HTTPException(409,str(e),headers={'Cache-Control':'no-store'}) from e
    except Exception as e:
        raise HTTPException(503,'Communications database unavailable',headers={'Cache-Control':'no-store'}) from e


@account_router.get('/notices')
def notices(user:dict=Depends(authenticated)):
    # This is a recipient-only view. Never accept account IDs/groups from query args.
    try:
        with closing(connect()) as db:
            data=store.inbox(db,account_id=user['account_id'],account_group=user['account_group'])
        return JSONResponse(data,headers={
            'Cache-Control':'private, no-store', 'Vary':'Cookie',
            'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer'})
    except Exception as e:
        raise HTTPException(503,'Account messages unavailable',headers={'Cache-Control':'no-store'}) from e


ACCOUNT_HEADERS={'Cache-Control':'private, no-store','Vary':'Cookie',
                 'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}


def _account_call(operation,*args,**kwargs):
    try:
        with closing(connect()) as db:
            result=operation(db,*args,**kwargs)
        return JSONResponse(result,headers=ACCOUNT_HEADERS)
    except LookupError as exc:
        raise HTTPException(404,'Message not found or reply unavailable',headers=ACCOUNT_HEADERS) from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc),headers=ACCOUNT_HEADERS) from exc
    except RuntimeError as exc:
        raise HTTPException(429 if 'rate limit' in str(exc) else 409,
                            str(exc),headers=ACCOUNT_HEADERS) from exc
    except Exception as exc:
        raise HTTPException(503,'Account messages unavailable',headers=ACCOUNT_HEADERS) from exc


@account_router.post('/notices/{notice_id}/reply',dependencies=[Depends(guard_origin)])
def reply_notice(notice_id:str,body:ReplyBody,user:dict=Depends(authenticated)):
    return _account_call(store.send_reply,sender_id=user['account_id'],
             sender_group=user['account_group'],notice_id=notice_id,
             body=body.body,request_id=body.client_request_id)


@account_router.post('/notices/{message_id}/hide',dependencies=[Depends(guard_origin)])
def hide_notice(message_id:str,body:HideBody,user:dict=Depends(authenticated)):
    return _account_call(store.hide_message,account_id=user['account_id'],
             account_group=user['account_group'],kind=body.message_type,message_id=message_id)


@admin_router.get('/admin/communications.js', include_in_schema=False)
def admin_js():
    return FileResponse(_UI/'communications.js',media_type='text/javascript',headers=HEADERS)


@admin_router.get('/admin/communications.css', include_in_schema=False)
def admin_css():
    return FileResponse(_UI/'communications.css',media_type='text/css',headers=HEADERS)


@admin_router.get('/api/v1/admin/communications')
def list_notices(limit:int=Query(40,ge=1,le=100),offset:int=Query(0,ge=0,le=100000),
                 include_archived:bool=False):
    return _admin_call(store.admin_list,limit=limit,offset=offset,include_archived=include_archived)


@admin_router.get('/api/v1/admin/communications/groups')
def list_groups():
    def op(db):return {'groups':store.groups(db)}
    return _admin_call(op)


@admin_router.post('/api/v1/admin/communications',dependencies=[Depends(guard_origin)])
def create_notice(body:DraftBody,user:dict=Depends(require_admin)):
    # Never publish directly on create. An explicit second action is necessary.
    return _admin_call(store.save_draft,actor=user['account_id'],data=body.model_dump())


@admin_router.put('/api/v1/admin/communications/{notice_id}',dependencies=[Depends(guard_origin)])
def edit_notice(notice_id:str,body:DraftBody,user:dict=Depends(require_admin)):
    return _admin_call(store.save_draft,notice_id=notice_id,actor=user['account_id'],
                       data=body.model_dump(),revision=body.revision)


@admin_router.post('/api/v1/admin/communications/{notice_id}/publish',dependencies=[Depends(guard_origin)])
def publish_notice(notice_id:str,body:StatusBody,user:dict=Depends(require_admin)):
    return _admin_call(store.change_status,actor=user['account_id'],notice_id=notice_id,
                       action='published',revision=body.revision)


@admin_router.post('/api/v1/admin/communications/{notice_id}/archive',dependencies=[Depends(guard_origin)])
def archive_notice(notice_id:str,body:StatusBody,user:dict=Depends(require_admin)):
    return _admin_call(store.change_status,actor=user['account_id'],notice_id=notice_id,
                       action='archived',revision=body.revision)
