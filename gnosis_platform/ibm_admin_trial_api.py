"""Explicitly gated admin-only IBM Future consultation admission.

Only creates a funded, durable queue entry; NEVER calls IBM Runtime or sends email.
This intentionally does not enable production customers or trust a browser email.
"""
from __future__ import annotations
import os
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from .auth_api import authenticated, guard_origin
from .db import connect
from .transactions import (begin_consultation, InsufficientCredits, CooldownActive,
                           RequestConflict, TransactionError)
from .ibm_future_queue import queue_request

router = APIRouter(prefix='/api/v1/ibm-future', tags=['ibm-admin-trial'])

class TrialInput(BaseModel):
    idempotency_key: str = Field(min_length=16, max_length=128)
    question: str = Field(default='', max_length=2000)
    inquiry_style: Literal['direct', 'meditative'] = 'direct'
    research_publication_consent: bool = False

@router.post('/admin-trial', dependencies=[Depends(guard_origin)], status_code=202)
def admit_admin_trial(body: TrialInput, user: dict = Depends(authenticated)):
    if os.getenv('GNOSIS_ENABLE_IBM_ADMIN_TRIAL') != 'YES' or not user.get('is_admin'):
        raise HTTPException(403, {'code': 'admin_trial_disabled'})
    try:
        with closing(connect()) as db:
            request = begin_consultation(
                db, account_id=user['account_id'], service_id='iching.quantum_future',
                idempotency_key=body.idempotency_key, question=body.question,
                inquiry_style=body.inquiry_style,
                research_publication_consent=body.research_publication_consent)
            # A retry after successful settlement is a read-only receipt.
            if request['status'] == 'pending':
                queue_request(db, request['request_id'])
            return {
                'state': request['status'], 'request_id': request['request_id'],
                'consultation_id': request['consultation_id'], 'credits_cost': 10,
                'hardware_submitted': False,
                'message': 'Authorized and queued; operator must submit hardware job separately.'
            }
    except InsufficientCredits as exc:
        raise HTTPException(402, {'code': 'insufficient_credits', 'message': str(exc)}) from exc
    except CooldownActive as exc:
        raise HTTPException(429, {'code': 'cooldown', 'next_eligible_at': exc.next_eligible_at}) from exc
    except RequestConflict as exc:
        raise HTTPException(409, {'code': 'idempotency_conflict', 'message': str(exc)}) from exc
    except TransactionError as exc:
        raise HTTPException(400, {'code': 'invalid_request', 'message': str(exc)}) from exc
