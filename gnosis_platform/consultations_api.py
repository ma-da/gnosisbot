"""Milestone 2B: authenticated read APIs and tightly gated sandbox consultation testing.

No external provider calls, and no public ability to create indefinitely pending
reservations. Sandbox submissions are immediately marked failed/refunded.
"""
import os
from fastapi import Response as _RuneResponse
from typing import Literal
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from .auth_api import authenticated, guard_origin
from .db import connect
from .registry import SERVICES
from .qci_execution import run_claimed_qci
from .nist_execution import run_claimed_nist
from .ibm_past_delivery import deliver_pending,available_count
from .transactions import (begin_consultation, finish_request, TransactionError,
                           InsufficientCredits, CooldownActive, RequestConflict)

router = APIRouter(prefix='/api/v1', tags=['gnosis-consultations'])

# Deliberately hard-disable providers until trustworthy adapters/workers exist.
PROVIDER_READY = frozenset()

class ConsultationInput(BaseModel):
    service_id: str = Field(max_length=80)
    idempotency_key: str = Field(min_length=16, max_length=128)
    question: str = Field(default='', max_length=2000)
    inquiry_style: Literal['direct', 'meditative'] = 'direct'
    research_publication_consent: bool = False


def _catalog_entry(p):
    if p.service_id.startswith('runes.'):
        from .rune_services import catalog_entry
        return catalog_entry(p,connect)
    past_ready = False
    if (p.service_id == 'iching.quantum_past'
        and os.environ.get('GNOSIS_ENABLE_IBM_PAST') == '1'):
        # Inventory is finite; catalog only advertises stock with approval.
        try:
            with closing(connect()) as inventory_db:
                past_ready = available_count(inventory_db) > 0
        except Exception:
            past_ready = False
    qci_live = (p.service_id == 'iching.qrng_private'
                and os.environ.get('GNOSIS_ENABLE_QCI') == '1'
                and bool(os.environ.get('QCI_API_TOKEN')))
    nist_live = (p.service_id == 'iching.qrng_public'
                 and os.environ.get('GNOSIS_ENABLE_NIST') == '1')
    return {
        'service_id': p.service_id, 'credits': p.credits,
        'min_balance': p.min_balance, 'cooldown_seconds': p.cooldown_seconds,
        'async_job': p.async_job, 'provider': p.provider,
        # A fallback isn't operational just because it's declared in registry.
        'fallback_active': False,
        'available': p.service_id == 'iching.classic' or qci_live or nist_live or past_ready,
        'availability': ('browser_local' if p.service_id == 'iching.classic'
                         else ('qci_live' if qci_live else ('nist_beacon_v2_enabled' if nist_live else ('ibm_past_approved_inventory' if past_ready else 'provider_not_connected')))),
    }


@router.get('/services/catalog')
def services_catalog():
    entries = [_catalog_entry(p) for p in SERVICES.values()]
    from .public_inventory import load_snapshot
    try:
        inventory = {x['service_id']: x for x in load_snapshot(connect)['engines']}
    except Exception:
        inventory = {}
    for entry in entries:
        if entry['service_id'].endswith('.quantum_past'):
            item = inventory.get(entry['service_id'])
            entry['inventory'] = item['counts'] if item else None
    return {'services': entries}


def _own_request(db, account_id, consultation_id):
    return db.execute('''SELECT c.consultation_id,c.application_id,c.question,
      c.inquiry_style,c.status,c.created_at,c.finished_at,
      c.research_publication_consent,r.request_id,r.service_id,r.provider,
      r.credits_cost,r.status AS request_status,r.started_at,r.completed_at
      FROM consultations c
      LEFT JOIN service_requests r ON r.consultation_id=c.consultation_id
      WHERE c.account_id=? AND c.consultation_id=?''', (account_id,consultation_id)).fetchone()


def _receipt(row):
    if row is None:
        raise HTTPException(404, 'Consultation not found')
    item=dict(row)
    item['research_publication_consent']=bool(item['research_publication_consent'])
    return item


@router.get('/consultations')
def consultation_history(user: dict=Depends(authenticated), limit: int=20, offset: int=0):
    if not (1 <= limit <= 100 and 0 <= offset <= 100000):
        raise HTTPException(422,'Invalid pagination')
    with closing(connect()) as db:
        rows=db.execute('''SELECT consultation_id FROM consultations
            WHERE account_id=? ORDER BY created_at DESC,consultation_id DESC
            LIMIT ? OFFSET ?''',(user['account_id'],limit,offset)).fetchall()
        total=db.execute('SELECT count(*) FROM consultations WHERE account_id=?',
                         (user['account_id'],)).fetchone()[0]
        items=[_receipt(_own_request(db,user['account_id'],r['consultation_id'])) for r in rows]
    return {'items':items, 'total':total, 'limit':limit, 'offset':offset}


@router.get('/consultations/{consultation_id}')
def consultation_status(consultation_id: str,user: dict=Depends(authenticated),response: _RuneResponse=None):
    if response is not None: response.headers['Cache-Control']='no-store'
    if len(consultation_id)!=32 or not all(x in '0123456789abcdef' for x in consultation_id):
        raise HTTPException(404,'Consultation not found')
    with closing(connect()) as db:
        row=_own_request(db,user['account_id'],consultation_id)
        item=_receipt(row)
        if item['status']=='completed':
            result=db.execute('''SELECT schema_version,reading_json,provenance_json
                FROM reading_results WHERE consultation_id=?''',(consultation_id,)).fetchone()
            if result:
                import json
                item['result']={'schema_version':result['schema_version'],
                                'reading':json.loads(result['reading_json']),
                                'provenance':json.loads(result['provenance_json'])}
    return item


def _map_transaction_error(exc):
    if isinstance(exc, InsufficientCredits):
        return HTTPException(402, {'code':exc.code,'message':str(exc)})
    if isinstance(exc,CooldownActive):
        return HTTPException(429, {'code':exc.code,'next_eligible_at':exc.next_eligible_at})
    if isinstance(exc,RequestConflict):
        return HTTPException(409, {'code':exc.code,'message':str(exc)})
    return HTTPException(400, {'code':exc.code,'message':str(exc)})


@router.post('/consultations',dependencies=[Depends(guard_origin)])
def create_consultation(body: ConsultationInput, user: dict=Depends(authenticated)):
    """Sandbox-only administrator probe. Never enqueue a provider job.

    Each new request is reserved then immediately failed/refunded before reply.
    Not a live consultation API until an audited execution worker is added.
    """
    # M5B rune submission. Never allow rune requests into I Ching sandbox.
    if body.service_id.startswith('runes.'):
        from .rune_api import submit_rune
        return submit_rune(body,user,connect)
    if body.service_id == 'iching.qrng_private' and os.environ.get('GNOSIS_ENABLE_QCI') == '1':
        if not os.environ.get('QCI_API_TOKEN'):
            raise HTTPException(503, {'code':'qci_not_configured'})
        try:
            with closing(connect()) as db:
                request=begin_consultation(db,account_id=user['account_id'],
                    service_id=body.service_id,idempotency_key=body.idempotency_key,
                    question=body.question,inquiry_style=body.inquiry_style,
                    research_publication_consent=body.research_publication_consent)
                if request['status']=='pending':
                    state,request=run_claimed_qci(db,request)
                else:
                    state=request['status']
                receipt=_receipt(_own_request(db,user['account_id'],request['consultation_id']))
                if state=='failed':
                    raise HTTPException(502, {'code':'qci_reading_failed',
                        'message':'Quantum randomness unavailable or invalid; no credits charged',
                        'consultation_id':request['consultation_id']})
                if state=='in_progress':
                    from fastapi.responses import JSONResponse
                    return JSONResponse(status_code=202,content={'state':'pending','receipt':receipt})
                if state=='completed':
                    return {'state':'completed','receipt':receipt,
                            'result':consultation_status(request['consultation_id'],user)['result']}
                raise HTTPException(409, {'code':'unexpected_request_state'})
        except TransactionError as exc:
            raise _map_transaction_error(exc) from exc
    if body.service_id == 'iching.qrng_public' and os.environ.get('GNOSIS_ENABLE_NIST') == '1':
        try:
            with closing(connect()) as db:
                request=begin_consultation(db,account_id=user['account_id'],
                    service_id=body.service_id,idempotency_key=body.idempotency_key,
                    question=body.question,inquiry_style=body.inquiry_style,
                    research_publication_consent=body.research_publication_consent)
                if request['status']=='pending':
                    state,request=run_claimed_nist(db,request)
                else:
                    state=request['status']
                receipt=_receipt(_own_request(db,user['account_id'],request['consultation_id']))
                if state=='failed':
                    raise HTTPException(502, {'code':'nist_reading_failed',
                        'message':'NIST public beacon unavailable or stale; no credits charged',
                        'consultation_id':request['consultation_id']})
                if state=='in_progress':
                    from fastapi.responses import JSONResponse
                    return JSONResponse(status_code=202,content={'state':'pending','receipt':receipt})
                if state=='completed':
                    return {'state':'completed','receipt':receipt,
                            'result':consultation_status(request['consultation_id'],user)['result']}
                raise HTTPException(409, {'code':'unexpected_nist_request_state'})
        except TransactionError as exc:
            raise _map_transaction_error(exc) from exc
    if body.service_id == 'iching.quantum_past':
        if os.environ.get('GNOSIS_ENABLE_IBM_PAST') != '1':
            raise HTTPException(503, {'code':'ibm_past_disabled'})
        try:
            with closing(connect()) as db:
                request=begin_consultation(db,account_id=user['account_id'],
                    service_id=body.service_id,idempotency_key=body.idempotency_key,
                    question=body.question,inquiry_style=body.inquiry_style,
                    research_publication_consent=body.research_publication_consent)
                outcome=deliver_pending(db,request['request_id'])
                receipt=_receipt(_own_request(db,user['account_id'],request['consultation_id']))
                if outcome['status']=='out_of_stock':
                    raise HTTPException(503, {'code':'ibm_past_inventory_exhausted',
                        'message':'No unused, approved IBM historical hardware samples remain. Credits released.'})
                if outcome['status']!='completed':
                    raise HTTPException(409, {'code':'ibm_past_not_completed'})
                return {'state':'completed','receipt':receipt,
                        'result':consultation_status(request['consultation_id'],user)['result']}
        except TransactionError as exc:
            raise _map_transaction_error(exc) from exc
    if os.environ.get('GNOSIS_ENABLE_CONSULTATION_SANDBOX')!='1' or not user['is_admin']:
        raise HTTPException(503, {'code':'providers_unavailable',
                                  'message':'Server-backed readings are not enabled'})
    if body.service_id not in SERVICES or body.service_id in ('iching.classic','iching.ai_enhancement'):
        raise HTTPException(400,{'code':'unsupported_service'})
    # Prevent source clients from overriding policy or choosing a real provider.
    try:
        with closing(connect()) as db:
            request=begin_consultation(db, account_id=user['account_id'],
                service_id=body.service_id,idempotency_key=body.idempotency_key,
                question=body.question,inquiry_style=body.inquiry_style,
                research_publication_consent=body.research_publication_consent)
            # Always fail, releasing held credits. Only operate on already-failed
            # idempotent replays; refuse if any unexpected state exists.
            if request['status']=='pending':
                request=finish_request(db,request['request_id'],success=False)
            elif request['status']!='failed':
                raise HTTPException(409, {'code':'existing_request_state_conflict'})
            receipt=_own_request(db,user['account_id'],request['consultation_id'])
            return {'sandbox':True, 'provider_called':False, 'credits_charged':0,
                    'receipt':_receipt(receipt)}
    except TransactionError as exc:
        raise _map_transaction_error(exc) from exc
