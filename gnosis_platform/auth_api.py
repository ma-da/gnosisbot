"""Opt-in FastAPI routes. Include from app.main only after local validation.

All endpoints are JSON; the private key never crosses the network.
"""
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from pydantic import BaseModel, Field
from .db import connect
from .credit_view import credit_view
from .identity import register, challenge, verify, session_account, revoke

router = APIRouter(prefix='/api/v1', tags=['gnosis-accounts'])
COOKIE = 'gnosis_session'

class Registration(BaseModel):
    public_key: str = Field(min_length=43,max_length=43)
    invitation: Optional[str] = None

class ChallengeInput(BaseModel):
    account_id: str = Field(min_length=64,max_length=64)

class VerifyInput(BaseModel):
    account_id: str
    challenge_id: str
    message: str = Field(max_length=1024)
    signature: str = Field(max_length=100)

# Origin policy applies to cookie-setting and state-changing API calls.
# Specify exact GNOSIS_WEB_ORIGIN for deployed site (e.g. https://gnosis.bot).
def guard_origin(request: Request):
    configured = os.environ.get('GNOSIS_WEB_ORIGIN','').rstrip('/')
    origin = request.headers.get('origin','').rstrip('/')
    if configured and origin != configured:
        raise HTTPException(403, 'Origin forbidden')
    # If no explicit origin policy configured, disallow cross-origin requests
    # by comparing origin with the request host; local scripts may omit Origin.
    if not configured and origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Origin forbidden')

@router.post('/accounts/register',dependencies=[Depends(guard_origin)])
def new_account(body: Registration):
    try:
        with connect() as db:
            return register(db, body.public_key, body.invitation)
    except ValueError:
        raise HTTPException(400,'Account registration failed')

@router.post('/auth/challenge',dependencies=[Depends(guard_origin)])
def new_challenge(body: ChallengeInput):
    try:
        with connect() as db:
            return challenge(db,body.account_id)
    except ValueError:
        raise HTTPException(400,'Unable to issue challenge')

@router.post('/auth/verify',dependencies=[Depends(guard_origin)])
def authenticate(body: VerifyInput, response: Response):
    try:
        with connect() as db:
            result = verify(db,body.account_id,body.challenge_id,body.message,body.signature)
    except ValueError:
        raise HTTPException(401,'Authentication failed')
    response.set_cookie(COOKIE,result['session_token'],httponly=True,
        secure=os.environ.get('GNOSIS_ALLOW_INSECURE_COOKIE')!='1',
        samesite='lax',max_age=90*86400,path='/')
    return {'authenticated': True,'account_id':result['account_id'],'expires_at':result['expires_at']}

def authenticated(request: Request):
    with connect() as db:
        row=session_account(db,request.cookies.get(COOKIE,''))
        if not row:
            raise HTTPException(401,'Authentication required')
        return dict(row)

@router.get('/accounts/me')
def me(user: dict=Depends(authenticated)):
    return {'verified':True,'account_id':user['account_id'],
            **credit_view(user),
            'is_admin':bool(user['is_admin']),'account_group':user['account_group']}

@router.get('/accounts/balance')
def balance(user: dict=Depends(authenticated)):
    return credit_view(user)

@router.post('/auth/logout',dependencies=[Depends(guard_origin)])
def logout(request: Request,response: Response):
    token=request.cookies.get(COOKIE,'')
    if token:
        with connect() as db:
            revoke(db,token)
    response.delete_cookie(COOKIE,path='/')
    return {'logged_out':True}
