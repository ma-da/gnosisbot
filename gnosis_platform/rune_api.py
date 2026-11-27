"""Use the existing authenticated, origin-guarded consultation POST and GETs."""
from contextlib import closing
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from .registry import SERVICES
from .rune_services import availability
from .rune_production import run_claimed
from .transactions import begin_consultation, TransactionError


def submit_rune(body,user,connect):
    from .consultations_api import _own_request,_receipt,_map_transaction_error,consultation_status
    if body.service_id not in SERVICES:
        raise HTTPException(400,{'code':'unsupported_service'})
    if body.service_id.endswith('.quantum_future'):
        from .future_trial import allowed as trial_allowed
        if not trial_allowed(user,body.service_id):
            raise HTTPException(403,{'code':'future_unavailable'})
        try:
            with closing(connect()) as db:
                req=begin_consultation(db,account_id=user['account_id'],service_id=body.service_id,
                    idempotency_key=body.idempotency_key,question=body.question,inquiry_style=body.inquiry_style,
                    research_publication_consent=body.research_publication_consent,admin_future_trial=True)
                cid=req['consultation_id'];receipt=_receipt(_own_request(db,user['account_id'],cid))
                if req['status']=='completed':
                    return JSONResponse(content={'state':'completed','receipt':receipt,'result':consultation_status(cid,user)['result']},headers={'Cache-Control':'no-store'})
                if req['status']=='failed':
                    raise HTTPException(502,{'code':'rune_reading_failed','consultation_id':cid})
                return JSONResponse(status_code=202,content={'state':'pending','receipt':receipt},headers={'Cache-Control':'no-store'})
        except TransactionError as exc:
            raise _map_transaction_error(exc) from exc
    allowed,why=availability(body.service_id,connect)
    if not allowed:
        # A completed/failed or staged Past request remains idempotently accessible
        # when inventory is exhausted. begin_consultation still checks the request hash.
        existing=None
        if body.service_id.endswith('.quantum_past'):
            with closing(connect()) as db:
                existing=db.execute("""SELECT r.request_id FROM service_requests r JOIN consultations c USING(consultation_id)
                    WHERE r.idempotency_key=? AND r.service_id=? AND c.account_id=?""",
                    (body.idempotency_key,body.service_id,user['account_id'])).fetchone()
        if existing is None:
            raise HTTPException(503,{'code':why,'message':'Rune source unavailable; no reading allocated or credits charged'})
    try:
        with closing(connect()) as db:
            request=begin_consultation(db,account_id=user['account_id'],service_id=body.service_id,
                idempotency_key=body.idempotency_key,question=body.question,inquiry_style=body.inquiry_style,
                research_publication_consent=body.research_publication_consent)
            cid=request['consultation_id']
            if not allowed and request['status']=='pending':
                staged=db.execute("SELECT status FROM rune_executions WHERE request_id=?",(request['request_id'],)).fetchone()
                if not staged or staged['status']!='staged':
                    raise HTTPException(503,{'code':why,'message':'Pending request requires operator reconciliation'})
            state=run_claimed(db,request)
            receipt=_receipt(_own_request(db,user['account_id'],cid))
            if state=='completed':
                return JSONResponse(content={'state':'completed','receipt':receipt,'result':consultation_status(cid,user)['result']},headers={'Cache-Control':'no-store'})
            if state=='failed':
                raise HTTPException(502,{'code':'rune_reading_failed','message':'Reading source failed; no credits charged; no fallback used','consultation_id':cid})
            if state=='in_progress':
                return JSONResponse(status_code=202,content={'state':'pending','receipt':receipt},headers={'Cache-Control':'no-store'})
            raise HTTPException(409,{'code':'unexpected_request_state','consultation_id':cid})
    except TransactionError as exc:
        raise _map_transaction_error(exc) from exc
