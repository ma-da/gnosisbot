"""Authenticated, origin-guarded public Solana wallet association API."""
from __future__ import annotations
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from .auth_api import authenticated, guard_origin
from .db import connect
from . import account_wallet as wallet

router=APIRouter(prefix='/api/v1/accounts/wallet',tags=['gnosis-account-wallet'])

class ChallengeBody(BaseModel):
    address:str=Field(min_length=32,max_length=44)
    model_config={'extra':'forbid'}

class VerifyBody(BaseModel):
    challenge_id:str=Field(min_length=32,max_length=32)
    signature:str=Field(min_length=80,max_length=96)
    model_config={'extra':'forbid'}


def _headers(response:Response):
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Robots-Tag']='noindex'


@router.get('')
def status(response:Response,user:dict=Depends(authenticated)):
    _headers(response)
    with closing(connect()) as db:
        data=wallet.active(db,user['account_id'])
    return {**data,'enabled':wallet.linking_enabled()}


@router.post('/challenge',dependencies=[Depends(guard_origin)])
def challenge(body:ChallengeBody,response:Response,user:dict=Depends(authenticated)):
    _headers(response)
    try:
        with closing(connect()) as db:
            return wallet.issue(db,account_id=user['account_id'],address=body.address)
    except wallet.WalletError as exc:
        raise HTTPException(422,str(exc)) from None


@router.post('/verify',dependencies=[Depends(guard_origin)])
def verify(body:VerifyBody,response:Response,user:dict=Depends(authenticated)):
    _headers(response)
    try:
        with closing(connect()) as db:
            return wallet.verify_link(db,account_id=user['account_id'],
                                      challenge_id=body.challenge_id,signature=body.signature)
    except wallet.WalletConflict as exc:
        raise HTTPException(409,str(exc)) from None
    except wallet.WalletError as exc:
        raise HTTPException(422,str(exc)) from None


@router.post('/unlink',dependencies=[Depends(guard_origin)])
def unlink(response:Response,user:dict=Depends(authenticated)):
    _headers(response)
    with closing(connect()) as db:
        return wallet.unlink(db,account_id=user['account_id'])


@router.get('/balances')
def balances(response:Response,user:dict=Depends(authenticated)):
    _headers(response)
    try:
        with closing(connect()) as db:
            return wallet.balances(db,account_id=user['account_id'])
    except wallet.WalletError as exc:
        raise HTTPException(404,str(exc)) from None
