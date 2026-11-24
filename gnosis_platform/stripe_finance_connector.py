"""Explicit read-only Stripe balance-transaction reporting from project start.

No Stripe SDK, no payment endpoints, no webhooks, and no credit ledger access.
Only vetted USD sales, refunds and fees enter the existing audited finance snapshot.
Unknown financial categories or incomplete pagination fail closed.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

BASE = 'https://api.stripe.com/v1/balance_transactions'
KEY_NAME = 'GNOSIS_STRIPE_REPORTING_KEY'
START = '2026-10-01'
MAX_PAGES = 100  # fail closed for more than 10,000 transactions; no partial sums.
MAX_RESPONSE = 2_097_152
SALES = {'charge'}
REFUNDS = {'refund'}
FEES = {'fee'}
# These affect Stripe cash movement without representing earned customer revenue.
EXCLUDED = {
 'payout','payout_reversal','transfer','transfer_reversal','topup','topup_reversal',
 'connect_reserved_funds','risk_reserved_funds','reserve_hold','reserve_release',
 'advance','advance_funding','anticipation_repayment',
 'inbound_transfer','inbound_transfer_reversal','fee_credit_funding',
}

class StripeReadError(ValueError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def connection_status(env=None):
    env = os.environ if env is None else env
    k=env.get(KEY_NAME, '')
    k=k.strip() if isinstance(k,str) else ''
    return {'configured':bool(k), 'live_restricted_key':k.startswith('rk_live_'),
            'automatic':True,'scope':'USD sales/refunds/fees since 2026-10-01 America/Chicago',
            'payments_enabled':False}

def _key(env=None):
    env=os.environ if env is None else env
    k=env.get(KEY_NAME, '')
    if not isinstance(k,str) or not k.strip():raise StripeReadError('reporting_key_not_configured')
    k=k.strip()
    if not k.startswith('rk_live_'):raise StripeReadError('live_restricted_key_required')
    return k

def project_start_epoch():
    return int(datetime(2026,10,1,tzinfo=ZoneInfo('America/Chicago')).timestamp())

def _get_page(key, params, opener=None):
    url=BASE+'?'+urlencode(params)
    req=Request(url,method='GET',headers={
      'Authorization':'Bearer '+key,'Accept':'application/json',
      'User-Agent':'GnosisFinancialReporting/1.0',
    })
    client=opener if opener is not None else build_opener(_NoRedirect())
    try:
        with client.open(req,timeout=15) as response:
            if response.status!=200:raise StripeReadError('unexpected_http_status')
            raw=response.read(MAX_RESPONSE+1)
            if len(raw)>MAX_RESPONSE:raise StripeReadError('response_too_large')
    except HTTPError as exc:
        raise StripeReadError('stripe_http_'+str(exc.code)) from None
    except (URLError,TimeoutError,OSError):
        raise StripeReadError('stripe_connection_failed') from None
    try: value=json.loads(raw)
    except (ValueError,UnicodeError):raise StripeReadError('invalid_stripe_response') from None
    if not isinstance(value,dict) or not isinstance(value.get('data'),list) or type(value.get('has_more')) is not bool:
        raise StripeReadError('invalid_stripe_page')
    return value

def _int(value):
    if type(value) is not int or abs(value)>1_000_000_000_00:raise StripeReadError('invalid_stripe_amount')
    return value

def _parse(rows,seen):
    gross=fees=refunds=0
    for record in rows:
        if not isinstance(record,dict) or record.get('object')!='balance_transaction':
            raise StripeReadError('invalid_stripe_transaction')
        ident=record.get('id')
        if not isinstance(ident,str) or not ident.startswith('txn_') or ident in seen:
            raise StripeReadError('repeated_or_invalid_transaction')
        seen.add(ident)
        cat=record.get('reporting_category')
        if not isinstance(cat,str):raise StripeReadError('missing_reporting_category')
        amount=_int(record.get('amount'))
        fee=_int(record.get('fee'))
        net=_int(record.get('net'))
        if amount-fee!=net or fee<0:raise StripeReadError('inconsistent_stripe_amounts')
        if cat in SALES|REFUNDS|FEES:
            if record.get('currency')!='usd':
                raise StripeReadError('non_usd_sales_or_fees')
            if cat in SALES:
                if amount<0:raise StripeReadError('unexpected_negative_sale')
                gross+=amount;fees+=fee
            elif cat in REFUNDS:
                if amount>0:raise StripeReadError('unexpected_positive_refund')
                refunds+=-amount;fees+=fee
            else:
                # Standalone Stripe processing fees are balance debits; positive
                # reversal represents a fee credit and reduces total fees.
                fees+=-net
        elif cat in EXCLUDED:
            continue
        else:
            # Disputes, adjustments, unrecognized categories: don't silently
            # misstate net revenue by excluding monetary activity.
            if amount!=0 or fee!=0:
                raise StripeReadError('unclassified_financial_category')
    return gross,fees,refunds

def collect(env=None, opener=None, now=None):
    key=_key(env)
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise StripeReadError('invalid_clock')
    until=int(now.timestamp())
    if until<project_start_epoch():raise StripeReadError('invalid_reporting_window')
    params={'limit':100,'created[gte]':project_start_epoch(),'created[lte]':until}
    seen=set();gross=fees=refunds=0
    for _ in range(MAX_PAGES):
        page=_get_page(key,params,opener=opener)
        rows=page['data']
        a,b,c=_parse(rows,seen)
        gross+=a;fees+=b;refunds+=c
        if not page['has_more']:
            if fees<0 or fees+refunds>gross:
                raise StripeReadError('snapshot_requires_manual_reconciliation')
            # Date and source are source-of-record metadata only, no tokens or IDs.
            return {'gross_cents':gross,'fees_cents':fees,'refunds_cents':refunds,
                    'as_of':now.astimezone(ZoneInfo('America/Chicago')).date().isoformat(),
                    'source':'Stripe Balance Transactions API · USD sales/fees/refunds · '+START+' · '+str(len(seen))+' rows'}
        if not rows:raise StripeReadError('empty_stripe_page_with_more')
        last=rows[-1]['id']
        if params.get('starting_after')==last:raise StripeReadError('stripe_pagination_stalled')
        params['starting_after']=last
    raise StripeReadError('stripe_pagination_limit')
