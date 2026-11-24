"""Authenticated editor API. Corpus-wide publishing is separately gated."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .admin_api import require_admin, HEADERS
from .auth_api import guard_origin
from . import interpretation_editor_store as store
from . import interpretation_editor_publish as releases

router=APIRouter(prefix='/api/v1/admin/editor',dependencies=[Depends(require_admin)],tags=['admin-editor'])


def reply(payload):return JSONResponse(payload,headers=HEADERS)


def handle(fn,*args,**kwargs):
    try:return reply(fn(*args,**kwargs))
    except store.DisabledError as exc:raise HTTPException(503,str(exc)) from exc
    except store.ConflictError as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    except OSError as exc:
        # Explicit message for systemd ProtectSystem/ReadWritePaths failures.
        # No internal paths or interpretation text are reflected to the client.
        raise HTTPException(503,'Editorial storage unavailable or read-only; check service sandbox and editor workspace permissions') from exc
    except (KeyError,IndexError,TypeError) as exc:raise HTTPException(422,'Corpus structure is incompatible with draft editor') from exc


@router.get('/catalog')
def get_catalog(q:str=Query('',max_length=120)):
    return handle(store.catalog,q)


@router.get('/record/{number}/{tradition}')
def get_record(number:int,tradition:str):
    return handle(store.get_record,number,tradition)


class Save(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_head:str|None=None
    fields:dict[str,str]=Field(max_length=50)


class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_head:str|None=None
    action:str=Field(max_length=24)
    revision_id:str|None=Field(default=None,max_length=32)


@router.post('/record/{number}/{tradition}/draft',dependencies=[Depends(guard_origin)])
def save_draft(number:int,tradition:str,payload:Save,user:dict=Depends(require_admin)):
    return handle(store.mutate,number,tradition,user['account_id'],'save',payload.expected_head,incoming=payload.fields)


@router.post('/record/{number}/{tradition}/action',dependencies=[Depends(guard_origin)])
def record_action(number:int,tradition:str,payload:Action,user:dict=Depends(require_admin)):
    if payload.action not in ('review','approve','unapprove','unreview','restore'):
        raise HTTPException(422,'Unsupported editorial action')
    return handle(store.mutate,number,tradition,user['account_id'],payload.action,
                  payload.expected_head,revision_id=payload.revision_id)


@router.get('/record/{number}/{tradition}/history/{revision_id}')
def get_history(number:int,tradition:str,revision_id:str):
    if len(revision_id)!=32 or any(c not in '0123456789abcdef' for c in revision_id):
        raise HTTPException(404,'Revision not found')
    return handle(store.history_revision,number,tradition,revision_id)


@router.get('/publication/preview')
def publication_preview():
    return handle(releases.preview)


class PublishRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_plan_token:str=Field(min_length=64,max_length=64)


@router.post('/publication/publish',dependencies=[Depends(guard_origin)])
def publication_publish(payload:PublishRequest,user:dict=Depends(require_admin)):
    return handle(releases.publish,actor=user['account_id'],expected_token=payload.expected_plan_token)


@router.get('/publication/history')
def publication_history(limit:int=Query(20,ge=1,le=100)):
    return handle(releases.history,limit)


@router.get('/publication/history/{release_id}')
def publication_history_detail(release_id:str):
    return handle(releases.history_detail,release_id)
