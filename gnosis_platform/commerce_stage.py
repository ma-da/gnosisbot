"""GNOSIS purchase-modal simulator. Zero external I/O, zero paid actions, zero credit mutations.

This is a deliberately isolated staging-preview service, NOT a payment processor.
Live orders will later use payment_orders + payment_events only after signed provider
verification and explicit operator go-live. Do not extrapolate this test state to money.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4
import json
import os
import re

METHODS = ('stripe', 'solana', 'rstory')
# Operator-approved launch denominations. STAGING previews, not real orders.
OFFERS = (
    ('pack-1', 1, '3.00'),
    ('pack-11', 11, '10.00'),
    ('pack-16', 16, '15.00'),
    ('pack-31', 31, '28.00'),
)
OFFER_MAP = {item[0]: item for item in OFFERS}
OFFER_ID = 'pack-16' # Legacy isolated test convenience
CREDITS = 16
TERMS_VERSION = 'staging-preview-2026-11'
DISCLAIMER = ('STAGING SIMULATION ONLY. No payment, token transfer, or credit issuance occurs. '
              'The displayed offer is for testing the interface, not an actual product offer.')
REFUND_SUMMARY = ('This is a simulated preview: no money or digital assets are collected, '
                  'no credits are issued, and therefore no refund is applicable to this test.')
HEADERS = {'Cache-Control': 'no-store, private', 'Pragma': 'no-cache', 'X-Content-Type-Options': 'nosniff'}

class StageError(ValueError):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def utc_now():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.isoformat(timespec='microseconds').replace('+00:00','Z')

def stage_enabled(user, environment=None):
    env = os.environ if environment is None else environment
    return env.get('GNOSIS_COMMERCE_STAGE_PREVIEW') == 'YES' and bool(user) and user.get('is_admin') == 1

def storefront(user, environment=None):
    enabled = stage_enabled(user, environment)
    return {
        'schema':'gnosis.credit-storefront.v1', 'enabled':enabled,
        'terms_version': TERMS_VERSION if enabled else None,
        'offers': [
            {'id':offer_id,'credits':credits,'usd_price':usd_price,
             'label':f'{credits} credits · ${usd_price} (preview only)'}
            for offer_id,credits,usd_price in OFFERS
        ] if enabled else [],
        'methods':[{'id':method,'enabled':enabled,'simulation_only':True} for method in METHODS],
        'staging_only':True, 'payments_enabled':False,
        'message':DISCLAIMER if enabled else 'Credit purchases are not yet available.'
    }


def validate_actor(user, environment=None):
    if not stage_enabled(user, environment):
        raise StageError('Credit purchases are not enabled', 503)
    account_id=user.get('account_id')
    if not isinstance(account_id,str) or not re.fullmatch(r'[0-9a-f]{64}',account_id):
        raise StageError('Account is unavailable',403)
    return account_id


def quote(db, user, offer_id, method, environment=None, current=None):
    account_id=validate_actor(user,environment)
    if type(offer_id) is not str or offer_id not in OFFER_MAP or method not in METHODS:
        raise StageError('Unavailable offer or method',422)
    _,credits,usd_price=OFFER_MAP[offer_id]
    at=current or utc_now()
    env=os.environ if environment is None else environment
    # Quote pricing only on explicit admin POST /quote, never on page load.
    # Admin-only staging has no daily quote ceiling. Real payable checkout will
    # require separate rate limiting and pricing-provider budget protection.
    from . import commerce_price_stage as pricing
    try:
        price_info=pricing.preview_pricing(method,usd_price,env,now=at,db=db if method == 'rstory' else None)
    except pricing.PricingError as ex:
        raise StageError(str(ex),503) from ex
    if price_info is None:
        raise StageError('Pricing preview unavailable',503)
    db.execute('BEGIN IMMEDIATE')
    try:
        # USD pack pricing is already fixed in the authenticated storefront.
        # Reuse an unexpired Stripe staging quote for repeated UI requests of
        # the same offer; this is NOT a new checkout or payment authorization.
        if method == 'stripe':
            prev=db.execute('''SELECT q.quote_id, q.expires_at, q.credits, q.total_display,
                q.fees_display, q.payment_detail, q.refund_summary, q.terms_version,
                s.quote_snapshot_json
              FROM gnosis_commerce_quotes AS q
              JOIN gnosis_commerce_price_snapshots AS s ON s.quote_id=q.quote_id
              WHERE q.account_id=? AND q.offer_id=? AND q.method='stripe'
                AND q.status='quoted' AND q.expires_at>?
              ORDER BY q.created_at DESC LIMIT 1''',
              (account_id,offer_id,iso(at))).fetchone()
            if prev and prev['credits']==credits and prev['terms_version']==TERMS_VERSION:
                try:
                    saved=json.loads(prev['quote_snapshot_json'])
                except (ValueError,TypeError):
                    saved=None
                if (isinstance(saved,dict) and saved.get('asset')=='USD' and
                    saved.get('usd_face_value')==usd_price and
                    saved.get('usd_payable_reference')==usd_price and
                    saved.get('asset_amount')==usd_price and
                    saved.get('discount_bps')==0 and
                    saved.get('price_source')=='configured-usd-face'):
                    db.commit()
                    return {
                        'schema':'gnosis.credit-quote.v1',
                        'quote_id':prev['quote_id'], 'expires_at':prev['expires_at'],
                        'staging_only':True, 'payments_enabled':False,
                        'offer_id':offer_id, 'method':method, 'credits':credits,
                        'total_display':prev['total_display'],
                        'fees_display':prev['fees_display'],
                        'payment_detail':prev['payment_detail'],
                        'refund_summary':prev['refund_summary'],
                        'terms_version':TERMS_VERSION, 'pricing_preview':saved,
                    }
        db.execute("UPDATE gnosis_commerce_quotes SET status='superseded' WHERE account_id=? AND status='quoted'",(account_id,))
        total_display,fees_display,payment_detail=pricing.quote_labels(price_info)
        payload={
            'offer_id':offer_id,'method':method,'credits':credits,
            'total_display':total_display,'fees_display':fees_display,
            'payment_detail':payment_detail,'refund_summary':REFUND_SUMMARY,
            'terms_version':TERMS_VERSION,
            'pricing_preview':price_info,
        }
        disclosure_hash=sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        qid=uuid4().hex
        expiry=iso(at+timedelta(minutes=15))
        db.execute('INSERT INTO gnosis_commerce_quotes (quote_id,account_id,offer_id,method,credits,total_display,fees_display,payment_detail,refund_summary,terms_version,disclosure_hash,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
          (qid,account_id,offer_id,method,credits,total_display,fees_display,payment_detail,
           REFUND_SUMMARY,TERMS_VERSION,disclosure_hash,iso(at),expiry,'quoted'))
        db.execute('INSERT INTO gnosis_commerce_price_snapshots (quote_id,asset,usd_face_value,usd_payable_reference,asset_unit_price_usd,asset_amount,discount_bps,valuation_policy,source_kind,fetched_at,quote_snapshot_json,is_payment) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)',
          (qid,price_info['asset'],price_info['usd_face_value'],price_info['usd_payable_reference'],
           price_info['asset_unit_price_usd'],price_info['asset_amount'],
           price_info['discount_bps'],price_info['policy'],price_info['price_source'],
           price_info['fetched_at'],json.dumps(price_info,sort_keys=True,separators=(',',':'))))
        db.commit()
        return {'schema':'gnosis.credit-quote.v1','quote_id':qid,'expires_at':expiry,
                'staging_only':True,'payments_enabled':False,**payload}
    except Exception:
        db.rollback()
        raise


def checkout(db, user, quote_id, idem, acceptance, environment=None, current=None, base_url=None):
    account_id=validate_actor(user,environment)
    if type(quote_id) is not str or not re.fullmatch(r'[0-9a-f]{32}',quote_id):
        raise StageError('Invalid quote',422)
    if type(idem) is not str or not 16 <= len(idem) <= 128 or not re.fullmatch(r'[A-Za-z0-9_.:-]+',idem):
        raise StageError('Invalid idempotency key',422)
    if not isinstance(acceptance,dict) or acceptance.get('accepted') is not True or acceptance.get('terms_version') != TERMS_VERSION:
        raise StageError('Current staging disclosure must be accepted',422)
    env = os.environ if environment is None else environment
    origin=(base_url or env.get('GNOSIS_WEB_ORIGIN') or '').rstrip('/')
    if not re.fullmatch(r'https://[a-z0-9.-]+(?::\d+)?',origin, re.I):
        raise StageError('Verified HTTPS origin is required for checkout preview',503)
    at=current or utc_now()
    db.execute('BEGIN IMMEDIATE')
    try:
        prior=db.execute('SELECT * FROM gnosis_commerce_previews WHERE idempotency_key=?',(idem,)).fetchone()
        if prior:
            if prior['quote_id'] != quote_id or prior['account_id'] != account_id:
                raise StageError('Idempotency key reused for a different quote',409)
            db.commit()
            return {'schema':'gnosis.credit-checkout.v1','status':'ready',
                    'checkout_url':f"{origin}/api/v1/accounts/credits/preview/{prior['preview_id']}",
                    'staging_only':True,'payments_enabled':False}
        q=db.execute('SELECT * FROM gnosis_commerce_quotes WHERE quote_id=? AND account_id=?',
                     (quote_id,account_id)).fetchone()
        if not q or q['status']!='quoted' or q['expires_at']<=iso(at) or q['terms_version']!=TERMS_VERSION:
            raise StageError('Quote is unavailable, superseded, or expired',409)
        pid=uuid4().hex
        db.execute('''INSERT INTO gnosis_commerce_previews
          (preview_id,quote_id,account_id,idempotency_key,terms_version,disclosure_hash,accepted_at,status)
          VALUES(?,?,?,?,?,?,?,'simulation_only')''',
          (pid,quote_id,account_id,idem,TERMS_VERSION,q['disclosure_hash'],iso(at)))
        db.execute("UPDATE gnosis_commerce_quotes SET status='previewed' WHERE quote_id=?",(quote_id,))
        db.commit()
        return {'schema':'gnosis.credit-checkout.v1','status':'ready',
                'checkout_url':f'{origin}/api/v1/accounts/credits/preview/{pid}',
                'staging_only':True,'payments_enabled':False}
    except Exception:
        db.rollback()
        raise


def preview(db, user, preview_id, environment=None):
    account_id=validate_actor(user,environment)
    if not re.fullmatch(r'[0-9a-f]{32}',preview_id or ''):
        raise StageError('Unknown preview',404)
    row=db.execute('''SELECT p.preview_id,p.accepted_at,p.status,q.credits,q.method,q.total_display
      FROM gnosis_commerce_previews p JOIN gnosis_commerce_quotes q ON p.quote_id=q.quote_id
      WHERE p.preview_id=? AND p.account_id=?''',(preview_id,account_id)).fetchone()
    if not row:
        raise StageError('Unknown preview',404)
    return dict(row)
