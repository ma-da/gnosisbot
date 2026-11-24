"""Authenticated credits purchase UX contract — staging preview exclusively."""
from contextlib import closing
from html import escape
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field
from .auth_api import authenticated, guard_origin
from .db import connect
from . import commerce_stage as stage

router=APIRouter(prefix='/api/v1/accounts/credits',tags=['credit-commerce-staging'])

class QuoteBody(BaseModel):
    offer_id: str = Field(min_length=1,max_length=90)
    method: str = Field(min_length=1,max_length=30)

class LegalAcceptance(BaseModel):
    accepted: bool
    terms_version: str = Field(min_length=1,max_length=80)

class CheckoutBody(BaseModel):
    quote_id: str = Field(min_length=32,max_length=32)
    idempotency_key: str = Field(min_length=16,max_length=128)
    legal_acceptance: LegalAcceptance


def respond(func):
    try:
        return JSONResponse(func(),headers=stage.HEADERS)
    except stage.StageError as ex:
        raise HTTPException(ex.status,str(ex),headers=stage.HEADERS) from ex
    except Exception as ex:
        raise HTTPException(503,'Commerce preview temporarily unavailable',headers=stage.HEADERS) from ex

@router.get('/storefront')
def storefront(user:dict=Depends(authenticated)):
    return JSONResponse(stage.storefront(user),headers=stage.HEADERS)

@router.post('/quote',dependencies=[Depends(guard_origin)])
def quote(body:QuoteBody,user:dict=Depends(authenticated)):
    def action():
        with closing(connect()) as db:
            return stage.quote(db,user,body.offer_id,body.method)
    return respond(action)

@router.post('/checkout',dependencies=[Depends(guard_origin)])
def checkout(body:CheckoutBody,user:dict=Depends(authenticated)):
    def action():
        with closing(connect()) as db:
            return stage.checkout(db,user,body.quote_id,body.idempotency_key,body.legal_acceptance.model_dump())
    return respond(action)

@router.get('/preview/{preview_id}',include_in_schema=False)
def preview(preview_id:str,user:dict=Depends(authenticated)):
    try:
        with closing(connect()) as db:
            item=stage.preview(db,user,preview_id)
    except stage.StageError as ex:
        raise HTTPException(ex.status,str(ex),headers=stage.HEADERS) from ex
    except Exception as ex:
        raise HTTPException(503,'Preview unavailable',headers=stage.HEADERS) from ex
    # This is intentionally NOT a payment page. No recipient, wallet, QR, secret, or JS.
    return HTMLResponse('''<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="robots" content="noindex,nofollow"><title>Gnosis · Checkout Preview</title>
    <style>body{margin:3rem auto;max-width:38rem;padding:0 1rem;font:16px system-ui,sans-serif;background:#faf9f5;color:#202527}h1{color:#1a5e63}a{color:#028090}</style>
    </head><body><h1>Checkout preview — no charge</h1><p><strong>STAGING ONLY.</strong> No payment was requested or processed, no wallet transfer occurred, and no credits were issued.</p>
    <p>Method previewed: <strong>'''+escape(item['method'])+'''</strong></p>
    <p>Proposed credits: <strong>'''+str(item['credits'])+'''</strong></p>
    <p>Accepted staging terms at: <strong>'''+escape(item['accepted_at'])+'''</strong></p>
    <p>This is not a receipt or completed purchase.</p>
    <p><a href="/account.html">Return to your account</a></p></body></html>''',headers={
        **stage.HEADERS,'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
        'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})
