"""Administrator-only encrypted Media CRM; no Resend sends or credit mutations."""
from __future__ import annotations
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .auth_api import guard_origin
from .admin_api import require_admin, HEADERS
from .db import connect
from . import media_crm as crm

router=APIRouter(prefix='/api/v1/admin/media',dependencies=[Depends(require_admin)],tags=['admin-media'])


def reply(data):return JSONResponse(data,headers=HEADERS)

class ContactBody(BaseModel):
    name: str = Field(default='',max_length=160)
    outlet: str = Field(default='',max_length=160)
    email: str = Field(default='',max_length=254)
    role: str = Field(default='',max_length=160)
    topics: str = Field(default='',max_length=500)
    notes: str = Field(default='',max_length=5000)
    published_url: str = Field(default='',max_length=800)
    status: str = Field(default='researching',max_length=24)
    next_followup: str | None = Field(default=None,max_length=10)
    claim_code_given: bool = False
    revision: int = Field(default=0,ge=0)

class ActivityBody(BaseModel):
    kind: str = Field(max_length=24)
    note: str = Field(min_length=1,max_length=2000)


def call(fn,*args,**kwargs):
    try:
        with closing(connect()) as db:return reply(fn(db,*args,**kwargs))
    except LookupError:raise HTTPException(404,'Media contact not found',headers={'Cache-Control':'no-store'})
    except ValueError as e:raise HTTPException(400,str(e),headers={'Cache-Control':'no-store'})
    except RuntimeError as e:raise HTTPException(409,str(e),headers={'Cache-Control':'no-store'})
    except Exception as e:raise HTTPException(503,'Media CRM unavailable',headers={'Cache-Control':'no-store'}) from e

@router.get('')
def index(query:str=Query('',max_length=160),status:str='',limit:int=Query(60,ge=1,le=100),offset:int=Query(0,ge=0,le=100000)):
    return call(crm.list_contacts,query=query,status=status,limit=limit,offset=offset)

@router.post('',dependencies=[Depends(guard_origin)])
def create(body:ContactBody,user:dict=Depends(require_admin)):
    return call(crm.save,body=body.model_dump(),actor=user['account_id'])

@router.get('/{contact_id}')
def get(contact_id:str):return call(crm.get,contact_id)

@router.put('/{contact_id}',dependencies=[Depends(guard_origin)])
def update(contact_id:str,body:ContactBody,user:dict=Depends(require_admin)):
    return call(crm.save,contact_id=contact_id,body=body.model_dump(),actor=user['account_id'],expected_revision=body.revision)

@router.get('/{contact_id}/activity')
def activity(contact_id:str,limit:int=Query(100,ge=1,le=200)):
    return call(crm.history,contact_id,limit)

@router.post('/{contact_id}/activity',dependencies=[Depends(guard_origin)])
def add_activity(contact_id:str,body:ActivityBody,user:dict=Depends(require_admin)):
    return call(crm.add_activity,contact_id=contact_id,actor=user['account_id'],kind=body.kind,note=body.note)
