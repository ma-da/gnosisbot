"""Service-neutral user account dashboard, activity and verified email enrollment."""
from __future__ import annotations
import json
import os
from contextlib import closing
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from .auth_api import authenticated,guard_origin
from .db import connect
from .account_email import (begin_email_verification,complete_email_verification,
                            email_status,stamp)

router=APIRouter(prefix='/api/v1/accounts',tags=['gnosis-account-hub'])

class NewEmail(BaseModel):
    email:str=Field(min_length=3,max_length=254)
class VerifyEmail(BaseModel):
    token:str=Field(min_length=24,max_length=256)

@router.get('/hub')
def account_hub(user:dict=Depends(authenticated),limit:int=30,offset:int=0):
    if not (1<=limit<=100 and 0<=offset<=100000):raise HTTPException(422,'Invalid pagination')
    with closing(connect()) as db:
        records=db.execute('''SELECT c.consultation_id,c.application_id,c.question,c.status,c.created_at,
          c.finished_at,r.service_id,r.provider,r.request_id,r.credits_cost,
          j.status AS hardware_status,j.backend,j.shots,
          o.status AS email_status
          FROM consultations c LEFT JOIN service_requests r ON r.consultation_id=c.consultation_id
          LEFT JOIN ibm_future_jobs j ON j.request_id=r.request_id
          LEFT JOIN gnosis_completion_outbox o ON o.request_id=r.request_id
          WHERE c.account_id=? ORDER BY c.created_at DESC,c.consultation_id DESC
          LIMIT ? OFFSET ?''',(user['account_id'],limit,offset)).fetchall()
        total=db.execute('SELECT count(*) FROM consultations WHERE account_id=?',(user['account_id'],)).fetchone()[0]
        pending=db.execute("SELECT count(*) FROM consultations WHERE account_id=? AND status='pending'",(user['account_id'],)).fetchone()[0]
        activities=[]
        for rec in records:
            item=dict(rec)
            # The hub is service-neutral: apps can add their own source and activity UI.
            item['open_url'] = ('/quantum-oracle.html?reading='+item['consultation_id']
                                if item['status']=='completed' and item['application_id']=='iching' else None)
            if item['status']=='completed' and item['application_id']=='runes':
                item['open_url']='/rune-oracle.html?reading='+item['consultation_id']
            item['status_url']='/account.html?view=activity&reading='+item['consultation_id']
            # No raw IBM shots or private encryption metadata in dashboard payload.
            activities.append(item)
        from .reading_resonance import attach_to_activity
        attach_to_activity(db, activities)
        contact=email_status(db,user['account_id'])
    from .account_app_registry import public_apps
    return {'account':{'credits':user['available'],'reserved':user['reserved'],
                       'total':user['available']+user['reserved'],
                       'account_group':user['account_group'],'is_admin':bool(user['is_admin'])},
            'email':contact, 'applications':public_apps(),
            'activity':{'items':activities,'total':total,'pending':pending,'limit':limit,'offset':offset}}

@router.post('/email/start',dependencies=[Depends(guard_origin)])
def start_email(body:NewEmail,user:dict=Depends(authenticated)):
    if os.environ.get('GNOSIS_ENABLE_EMAIL_VERIFICATION')!='YES':
        raise HTTPException(503,'Email verification not enabled')
    for key in ('RESEND_API_KEY','GNOSIS_RESEND_FROM','GNOSIS_CONTACT_ENCRYPTION_KEY'):
        if not os.environ.get(key):raise HTTPException(503,'Email delivery is not configured')
    with closing(connect()) as db:
        try:token,addr=begin_email_verification(db,account_id=user['account_id'],email=body.email)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    base=os.environ.get('GNOSIS_PUBLIC_BASE_URL','https://gnosis.bot')
    if not base.startswith('https://'):raise HTTPException(503,'Public URL must be HTTPS')
    link=base.rstrip('/')+'/account.html?verify_email='+token
    from .ibm_trial_email import submit_resend
    msg={'from':os.environ['GNOSIS_RESEND_FROM'],'to':[addr],
         'subject':'Verify your Gnosis email address',
         'text':'Verify that you own this email to receive completed Gnosis reading notifications.\n\n'+link+
                '\n\nThe link expires in one hour. Your account private key is never needed by email.'}
    try:
        submit_resend(api_key=os.environ['RESEND_API_KEY'],message=msg,
                      idem_key='gnosis-verify-'+__import__('hashlib').sha256(token.encode()).hexdigest()[:32])
    except Exception as exc:
        # Token remains valid; provider outcome may be ambiguous. Never log token or address.
        raise HTTPException(502,'Verification mail delivery needs review; consult Resend logs') from exc
    return {'sent':True,'message':'Check your inbox and verify your address within one hour.'}

@router.post('/email/confirm',dependencies=[Depends(guard_origin)])
def confirm_email(body:VerifyEmail,user:dict=Depends(authenticated)):
    try:
        with closing(connect()) as db:
            return complete_email_verification(db,account_id=user['account_id'],token=body.token)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc

from .reading_resonance import router as _resonance_router
router.include_router(_resonance_router)
