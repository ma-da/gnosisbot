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
    from .future_trial import allowed
    if not allowed(user,'iching.quantum_future'):
        raise HTTPException(403, {'code': 'future_unavailable'})
    try:
        with closing(connect()) as db:
            request = begin_consultation(
                db, account_id=user['account_id'], service_id='iching.quantum_future',
                idempotency_key=body.idempotency_key, question=body.question,
                inquiry_style=body.inquiry_style,
                research_publication_consent=body.research_publication_consent, admin_future_trial=True)
            from .future_auto_policy import enabled as automatic_enabled
            return {
                'state': request['status'], 'request_id': request['request_id'],
                'consultation_id': request['consultation_id'], 'credits_cost': 10,
                'hardware_submitted': False,
                'message': ('Reading accepted and queued for automatic hardware processing.' if automatic_enabled() else 'Authorized and queued; operator must submit hardware job separately.')
            }
    except InsufficientCredits as exc:
        raise HTTPException(402, {'code': 'insufficient_credits', 'message': str(exc)}) from exc
    except CooldownActive as exc:
        raise HTTPException(429, {'code': 'cooldown', 'next_eligible_at': exc.next_eligible_at}) from exc
    except RequestConflict as exc:
        raise HTTPException(409, {'code': 'idempotency_conflict', 'message': str(exc)}) from exc
    except TransactionError as exc:
        from .transactions import FutureCapacityError
        if isinstance(exc,FutureCapacityError):raise HTTPException(503, {'code':exc.code,'message':str(exc)}) from exc
        raise HTTPException(400, {'code': 'invalid_request', 'message': str(exc)}) from exc
