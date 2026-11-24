"""Authenticated credit administration; explicit mutations only."""
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .admin_api import HEADERS,require_admin
from .auth_api import guard_origin,authenticated
from .db import connect
from . import credit_supply as supply
from .identity import grant

router=APIRouter(prefix='/api/v1/admin/credits',dependencies=[Depends(require_admin)],tags=['admin-credits'])
claims=APIRouter(prefix='/api/v1/credits',dependencies=[Depends(authenticated)],tags=['credits'])

class BatchBody(BaseModel):
    group: str
    quantity: int=Field(ge=1,le=100)
    credits_each: int=Field(ge=1,le=100000)
    expires_days: int=Field(default=90,ge=1,le=365)
    idempotency_key: str=Field(min_length=16,max_length=128)

class GrantBody(BaseModel):
    account_id: str=Field(min_length=64,max_length=64)
    credits: int=Field(ge=1,le=100000)
    reason: str=Field(min_length=6,max_length=240)
    idempotency_key: str=Field(min_length=16,max_length=128)

class RedeemBody(BaseModel):
    claim_code: str=Field(min_length=32,max_length=128)

def respond(value):return JSONResponse(value,headers=HEADERS)

def call(fn):
    try:
        with closing(connect()) as db:
            return respond(fn(db))
    except ValueError as e:raise HTTPException(400,str(e)) from e
    except RuntimeError as e:raise HTTPException(409,str(e)) from e
    except Exception as e:raise HTTPException(503,'Credits service unavailable') from e

@router.get('/summary')
def get_summary():return call(supply.summary)

@router.get('/batches')
def get_batches():return call(supply.batches)

@router.get('/accounts')
def get_accounts():return call(supply.accounts)

@router.get('/leaderboard')
def get_leaderboard():return call(supply.leaderboard)

@router.post('/batches',dependencies=[Depends(guard_origin)])
def issue(body:BatchBody,user:dict=Depends(require_admin)):
    return call(lambda db:supply.create_batch(db,actor=user['account_id'],group=body.group,
       quantity=body.quantity,credits_each=body.credits_each,
       expires_days=body.expires_days,idem=body.idempotency_key))

@router.post('/grants',dependencies=[Depends(guard_origin)])
def issue_grant(body:GrantBody,user:dict=Depends(require_admin)):
    def work(db):
        # Actor checked by per-request administrator dependency, but also recorded in ledger.
        created=grant(db,body.account_id,body.credits,user['account_id'],
                      'admin:'+body.reason,body.idempotency_key)
        return {'created':created}
    return call(work)

@claims.post('/redeem',dependencies=[Depends(guard_origin)])
def redeem(body:RedeemBody,user:dict=Depends(authenticated)):
    return call(lambda db:supply.redeem_existing(db,account_id=user['account_id'],token=body.claim_code))
