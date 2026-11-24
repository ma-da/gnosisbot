"""Administrator-only financial register. No Stripe, Solana or provider network calls."""
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from .auth_api import guard_origin
from .admin_api import require_admin, HEADERS
from .db import connect
from . import financials as f

router=APIRouter(prefix='/api/v1/admin/finance',tags=['admin-financials'],dependencies=[Depends(require_admin)])

def reply(value):return JSONResponse(value,headers=HEADERS)

def failure(e):return HTTPException(422,str(e),headers={'Cache-Control':'no-store'})

@router.get('')
def status():
    with closing(connect()) as db:return reply(f.summary(db))

@router.get('/audit')
def audit():
    with closing(connect()) as db:
        return reply({'records':[dict(r) for r in db.execute('''SELECT audit_id,actor,action,entity_id,at FROM gnosis_finance_audit ORDER BY at DESC,audit_id DESC LIMIT 100''')]})

@router.post('/items',dependencies=[Depends(guard_origin)])
def create_item(body:dict,user:dict=Depends(require_admin)):
    try:
        with closing(connect()) as db:return reply(f.save_item(db,user['account_id'],body))
    except (f.FinanceError,ValueError) as e:raise failure(e)

@router.put('/items/{item_id}',dependencies=[Depends(guard_origin)])
def update_item(item_id:str,body:dict,user:dict=Depends(require_admin)):
    try:
        with closing(connect()) as db:return reply(f.save_item(db,user['account_id'],body,item_id))
    except (f.FinanceError,ValueError) as e:raise failure(e)

@router.delete('/items/{item_id}',dependencies=[Depends(guard_origin)])
def delete_item(item_id:str,user:dict=Depends(require_admin)):
    try:
        with closing(connect()) as db:f.remove_item(db,user['account_id'],item_id)
        return reply({'removed':True})
    except (f.FinanceError,ValueError) as e:raise failure(e)

@router.put('/providers/{provider_id}',dependencies=[Depends(guard_origin)])
def set_provider(provider_id:str,body:dict,user:dict=Depends(require_admin)):
    try:
        if body.get('provider_id') != provider_id:raise f.FinanceError('Provider ID mismatch')
        with closing(connect()) as db:return reply(f.save_provider(db,user['account_id'],body))
    except (f.FinanceError,ValueError) as e:raise failure(e)

@router.delete('/providers/{provider_id}',dependencies=[Depends(guard_origin)])
def delete_provider(provider_id:str,user:dict=Depends(require_admin)):
    try:
        with closing(connect()) as db:f.remove_provider(db,user['account_id'],provider_id)
        return reply({'removed':True})
    except (f.FinanceError,ValueError) as e:raise failure(e)

@router.put('/stripe',dependencies=[Depends(guard_origin)])
def stripe(body:dict,user:dict=Depends(require_admin)):
    try:
        with closing(connect()) as db:return reply(f.save_stripe(db,user['account_id'],body))
    except (f.FinanceError,ValueError) as e:raise failure(e)

@router.put('/wallet',dependencies=[Depends(guard_origin)])
def wallet(body:dict,user:dict=Depends(require_admin)):
    try:
        with closing(connect()) as db:return reply(f.save_wallet_stub(db,user['account_id'],body))
    except (f.FinanceError,ValueError) as e:raise failure(e)


# Explicit admin action only. Loading the admin page never calls external providers.
@router.get('/connections')
def provider_connections():
    from .finance_provider_connectors import connection_status
    return reply({'providers':connection_status()})

@router.post('/providers/{provider_id}/refresh',dependencies=[Depends(guard_origin)])
def provider_refresh(provider_id:str,user:dict=Depends(require_admin)):
    from .finance_provider_connectors import refresh,ConnectorError
    if provider_id not in ('deepseek','deepinfra'):
        raise HTTPException(422,'No supported automatic balance endpoint',headers={'Cache-Control':'no-store'})
    try:
        payload=refresh(provider_id)  # HTTPS GET before opening database transaction
        with closing(connect()) as db:
            # Reuse the existing audited finance provider write path.
            return reply(f.save_provider(db,user['account_id'],payload))
    except ConnectorError as exc:
        # Only a fixed error code may leave the server; never send provider payloads.
        raise HTTPException(503,'Provider refresh: '+exc.code,headers={'Cache-Control':'no-store'}) from None
    except f.FinanceError as exc:
        raise failure(exc) from None


# Stripe reporting only: fixed GET endpoint to read Stripe, then audited local snapshot.
# Never enables Checkout, webhooks, payment fulfillment or credit minting.
@router.get('/stripe/connection')
def stripe_connection():
    from .stripe_finance_connector import connection_status
    return reply(connection_status())

@router.post('/stripe/refresh',dependencies=[Depends(guard_origin)])
def stripe_refresh(user:dict=Depends(require_admin)):
    from .stripe_finance_connector import collect, StripeReadError
    try:
        payload = collect()  # HTTPS GET requests only; nothing written until complete.
    except StripeReadError as exc:
        raise HTTPException(503,'Stripe reporting: '+exc.code,headers={'Cache-Control':'no-store'}) from None
    try:
        with closing(connect()) as db:
            return reply(f.save_stripe(db,user['account_id'],payload))
    except (f.FinanceError,ValueError) as exc:
        raise failure(exc) from None
