"""Gnosis venture finances: admin-only, auditable source of record and noncash valuation.

All cash values use integer cents; provider quantities and USD conversion rates are
Decimal text. Source metadata is NOT a credential. No network calls occur here.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4
from zoneinfo import ZoneInfo
from .admin_metrics import get_snapshot

START = '2026-10-01'
CENTS = Decimal('100')
ITEM_KINDS = ('monthly_cost', 'one_time_cost', 'revenue', 'monthly_revenue')
STATUS = {
    'monthly_cost': ('active','planned','disabled'),
    'one_time_cost': ('planned','incurred','disabled'),
    'revenue': ('planned','received','disabled'),
    'monthly_revenue': ('active','planned','disabled'),
}
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

class FinanceError(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def money(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 1_000_000_000_00:
        raise FinanceError('Amount must be integer USD cents in permitted range')
    return value

def safe_text(value, label, min_len=0, max_len=160):
    if not isinstance(value, str) or len(value.strip()) < min_len or len(value) > max_len:
        raise FinanceError(f'Invalid {label}')
    if any(ord(ch) < 32 and ch not in '\t' for ch in value):
        raise FinanceError(f'Invalid {label}')
    return value.strip()

def parse_date(value, required=False):
    if value in ('', None):
        if required: raise FinanceError('Date required')
        return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise FinanceError('Date must be YYYY-MM-DD')
    try: date.fromisoformat(value)
    except ValueError as exc: raise FinanceError('Invalid date') from exc
    return value

def decimal_text(value, label, may_be_none=True, max_value=Decimal('1000000000')):
    if value in ('', None):
        if may_be_none:return None
        raise FinanceError(f'Missing {label}')
    if isinstance(value, bool) or isinstance(value, (dict,list)):
        raise FinanceError(f'Invalid {label}')
    try: n=Decimal(str(value))
    except InvalidOperation as exc: raise FinanceError(f'Invalid {label}') from exc
    if not n.is_finite() or n<0 or n>max_value:
        raise FinanceError(f'Invalid {label}')
    return str(n)

def _audit(db, actor, action, entity_id, before=None, after=None):
    db.execute('''INSERT INTO gnosis_finance_audit(audit_id,actor,action,entity_id,before_json,after_json)
      VALUES(?,?,?,?,?,?)''',(uuid4().hex,actor,action,entity_id,
         json.dumps(before,sort_keys=True) if before is not None else None,
         json.dumps(after,sort_keys=True) if after is not None else None))

def _row(db, table, id_field, id_value):
    r=db.execute(f'SELECT * FROM {table} WHERE {id_field}=?',(id_value,)).fetchone()
    return dict(r) if r else None

def _month_count(first, last, cutoff):
    """Monthly cycles charged on start day-of-month, clamped for short months."""
    start=date.fromisoformat(first)
    end=date.fromisoformat(cutoff)
    if last and date.fromisoformat(last)<end:end=date.fromisoformat(last)
    if end < start:return 0
    from calendar import monthrange
    n=0
    y,m=start.year,start.month
    while (y,m)<=(end.year,end.month):
        day=min(start.day,monthrange(y,m)[1])
        due=date(y,m,day)
        if start<=due<=end:n+=1
        m+=1
        if m==13:y+=1;m=1
    return n

def financial_rows(db, include_deleted=False):
    q='SELECT * FROM gnosis_finance_items'
    if not include_deleted:q+=' WHERE deleted_at IS NULL'
    q+=' ORDER BY kind,name,item_id'
    return [dict(r) for r in db.execute(q)]

def provider_rows(db, include_deleted=False):
    q='SELECT * FROM gnosis_finance_provider_balances'
    if not include_deleted:q+=' WHERE deleted_at IS NULL'
    q+=' ORDER BY name,provider_id'
    return [dict(r) for r in db.execute(q)]

def summary(db, *, today=None):
    today = today or datetime.now(ZoneInfo('America/Chicago')).date().isoformat()
    project_start=db.execute('SELECT project_start FROM gnosis_finance_settings WHERE singleton=1').fetchone()[0]
    items=financial_rows(db)
    incurred_cost=0; recurring_cost=0; one_time_cost=0; planned_cost=0; other_revenue=0
    for r in items:
        amount=r['amount_cents']
        if r['kind']=='monthly_cost':
            if r['status']=='active':
                v=amount*_month_count(max(project_start,r['starts_on']),r['ends_on'],today)
                recurring_cost+=v; incurred_cost+=v
        elif r['kind']=='monthly_revenue':
            if r['status']=='active':
                other_revenue+=amount*_month_count(max(project_start,r['starts_on']),r['ends_on'],today)
        elif r['kind']=='one_time_cost':
            if r['status']=='incurred' and r['occurs_on']<=today and r['occurs_on']>=project_start:
                incurred_cost+=amount;one_time_cost+=amount
            elif r['status']=='planned':planned_cost+=amount
        elif r['kind']=='revenue' and r['status']=='received' and project_start<=r['occurs_on']<=today:
            other_revenue+=amount
    stripe=_row(db,'gnosis_finance_stripe','singleton',1)
    if stripe:
        stripe['net_cents']=stripe['gross_cents']-stripe['fees_cents']-stripe['refunds_cents']
    provider_values=[]; known_value=0; incomplete=[]
    ibm=get_snapshot(db,'ibm_instance')
    seconds=ibm.get('usage_remaining_seconds')
    ibm_value=None
    try:
        if seconds is not None:
            q=Decimal(str(seconds))
            if q.is_finite() and q>=0:
                ibm_value=int((q * Decimal('1.60') * CENTS).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except InvalidOperation:pass
    if ibm_value is not None:known_value+=ibm_value
    else:incomplete.append('IBM instance balance')
    if ibm.get('stale'):incomplete.append('IBM snapshot stale')
    provider_values.append(dict(provider_id='ibm',name='IBM Quantum',units='QPU seconds',quantity=str(seconds) if ibm_value is not None else None,
        rate_usd='1.60',valuation_cents=ibm_value,as_of=ibm.get('as_of'),stale=ibm.get('stale',True),state='reported' if ibm_value is not None else 'unknown',source='IBM runtime allocation snapshot',automatic=True))
    for r in provider_rows(db):
        v=None
        if r['state']=='reported' and r['quantity'] is not None and r['rate_usd'] is not None:
            v=int((Decimal(r['quantity'])*Decimal(r['rate_usd'])*CENTS).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            known_value+=v
        elif r['state']=='unknown':incomplete.append(r['name']+' balance')
        provider_values.append(dict(provider_id=r['provider_id'],name=r['name'],units=r['units'],quantity=r['quantity'],rate_usd=r['rate_usd'],
            valuation_cents=v,as_of=r['observed_at'],state=r['state'],source=r['source'],notes=r['notes'],automatic=False))
    cash_known=other_revenue-incurred_cost+(stripe['net_cents'] if stripe else 0)
    return dict(as_of=today,project_start=project_start,recurring_cost_cents=recurring_cost,
       monthly_current_cents=sum(r['amount_cents'] for r in items if r['kind']=='monthly_cost' and r['status']=='active' and r['starts_on']<=today and (not r['ends_on'] or r['ends_on']>=today)),
       one_time_cost_cents=one_time_cost,planned_cost_cents=planned_cost,total_incurred_cost_cents=incurred_cost,
       other_revenue_cents=other_revenue,stripe=stripe if stripe else dict(status='not_connected',gross_cents=None,fees_cents=None,refunds_cents=None,net_cents=None,as_of=None),
       cash_known_net_cents=cash_known,cash_complete=bool(stripe),provider_known_value_cents=known_value,
       project_known_net_cents=cash_known+known_value,valuation_complete=not incomplete and bool(stripe),
       missing=incomplete+([] if stripe else ['Stripe receipts']),providers=provider_values,
       items=items,settings=dict(_row(db,'gnosis_finance_settings','singleton',1)))

def validate_item(payload):
    kind=payload.get('kind')
    if kind not in ITEM_KINDS:raise FinanceError('Unknown item kind')
    status=payload.get('status')
    if status not in STATUS[kind]:raise FinanceError('Invalid item status')
    v=dict(name=safe_text(payload.get('name'),'name',1,120),category=safe_text(payload.get('category','General'),'category',1,70),
        kind=kind,amount_cents=money(payload.get('amount_cents')),status=status,
        starts_on=parse_date(payload.get('starts_on'),required=kind in ('monthly_cost','monthly_revenue')),
        ends_on=parse_date(payload.get('ends_on')),
        occurs_on=parse_date(payload.get('occurs_on'),required=(kind=='one_time_cost' and status=='incurred') or (kind=='revenue' and status=='received')),
        memo=safe_text(payload.get('memo',''),'memo',0,500))
    if v['starts_on'] and v['ends_on'] and v['ends_on']<v['starts_on']:raise FinanceError('End precedes start')
    return v

def save_item(db, actor, payload, item_id=None):
    v=validate_item(payload)
    db.execute('BEGIN IMMEDIATE')
    try:
        before=_row(db,'gnosis_finance_items','item_id',item_id) if item_id else None
        if item_id and (not before or before['deleted_at']):raise FinanceError('Item unavailable')
        if item_id:
            db.execute('''UPDATE gnosis_finance_items SET name=:name,category=:category,kind=:kind,amount_cents=:amount_cents,
               status=:status,starts_on=:starts_on,ends_on=:ends_on,occurs_on=:occurs_on,memo=:memo,
               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE item_id=:id''',dict(v,id=item_id))
        else:
            item_id=uuid4().hex
            db.execute('''INSERT INTO gnosis_finance_items(item_id,name,category,kind,amount_cents,status,starts_on,ends_on,occurs_on,memo)
                VALUES(:id,:name,:category,:kind,:amount_cents,:status,:starts_on,:ends_on,:occurs_on,:memo)''',dict(v,id=item_id))
        after=_row(db,'gnosis_finance_items','item_id',item_id)
        _audit(db,actor,'update_item' if before else 'create_item',item_id,before,after)
        db.commit();return after
    except Exception:db.rollback();raise

def remove_item(db, actor, item_id):
    db.execute('BEGIN IMMEDIATE')
    try:
        before=_row(db,'gnosis_finance_items','item_id',item_id)
        if not before or before['deleted_at']:raise FinanceError('Item unavailable')
        db.execute('UPDATE gnosis_finance_items SET deleted_at=?,updated_at=? WHERE item_id=?',(now(),now(),item_id))
        after=_row(db,'gnosis_finance_items','item_id',item_id)
        _audit(db,actor,'remove_item',item_id,before,after);db.commit()
    except Exception:db.rollback();raise

def validate_provider(payload):
    ident=safe_text(payload.get('provider_id'),'provider ID',1,40)
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',ident) or ident=='ibm':raise FinanceError('Invalid or reserved provider ID')
    state=payload.get('state')
    if state not in ('unknown','reported','unlimited','disabled'):raise FinanceError('Invalid provider state')
    v=dict(provider_id=ident,name=safe_text(payload.get('name'),'provider',1,120),
       units=safe_text(payload.get('units'),'units',1,50),state=state,
       quantity=decimal_text(payload.get('quantity'),'balance'),rate_usd=decimal_text(payload.get('rate_usd'),'unit rate',max_value=Decimal('1000000')),
       source=safe_text(payload.get('source','operator'),'source',1,120),
       observed_at=parse_date(payload.get('observed_at')),
       notes=safe_text(payload.get('notes',''),'notes',0,500))
    if state=='reported' and (v['quantity'] is None or v['rate_usd'] is None):raise FinanceError('Reported balance requires quantity and USD/unit rate')
    return v

def save_provider(db, actor, payload):
    v=validate_provider(payload)
    db.execute('BEGIN IMMEDIATE')
    try:
        before=_row(db,'gnosis_finance_provider_balances','provider_id',v['provider_id'])
        if before and before['deleted_at']:raise FinanceError('Provider removed; use a new identifier')
        if before:
            db.execute('''UPDATE gnosis_finance_provider_balances SET name=:name,units=:units,quantity=:quantity,
                 rate_usd=:rate_usd,state=:state,source=:source,observed_at=:observed_at,notes=:notes,
                 updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE provider_id=:provider_id''',v)
        else:
            db.execute('''INSERT INTO gnosis_finance_provider_balances(provider_id,name,units,quantity,rate_usd,state,source,observed_at,notes)
              VALUES(:provider_id,:name,:units,:quantity,:rate_usd,:state,:source,:observed_at,:notes)''',v)
        after=_row(db,'gnosis_finance_provider_balances','provider_id',v['provider_id'])
        _audit(db,actor,'save_provider',v['provider_id'],before,after)
        db.commit();return after
    except Exception:db.rollback();raise

def remove_provider(db, actor, provider_id):
    if provider_id=='ibm':raise FinanceError('IBM balance is supplied automatically')
    db.execute('BEGIN IMMEDIATE')
    try:
        before=_row(db,'gnosis_finance_provider_balances','provider_id',provider_id)
        if not before or before['deleted_at']:raise FinanceError('Provider unavailable')
        db.execute('UPDATE gnosis_finance_provider_balances SET deleted_at=?,updated_at=? WHERE provider_id=?',(now(),now(),provider_id))
        _audit(db,actor,'remove_provider',provider_id,before,_row(db,'gnosis_finance_provider_balances','provider_id',provider_id))
        db.commit()
    except Exception:db.rollback();raise

def save_stripe(db,actor,payload):
    fields=('gross_cents','fees_cents','refunds_cents')
    vals={k:money(payload.get(k)) for k in fields}
    if vals['fees_cents']+vals['refunds_cents']>vals['gross_cents']:
        raise FinanceError('Stripe fees and refunds exceed incoming receipts')
    as_of=parse_date(payload.get('as_of'),required=True)
    source=safe_text(payload.get('source'),'Stripe snapshot source',4,150)
    db.execute('BEGIN IMMEDIATE')
    try:
        before=_row(db,'gnosis_finance_stripe','singleton',1)
        # Manual provider snapshots are cumulative from project start.
        db.execute('''INSERT INTO gnosis_finance_stripe(singleton,gross_cents,fees_cents,refunds_cents,as_of,source)
          VALUES(1,:gross_cents,:fees_cents,:refunds_cents,:as_of,:source)
          ON CONFLICT(singleton) DO UPDATE SET gross_cents=excluded.gross_cents,
          fees_cents=excluded.fees_cents,refunds_cents=excluded.refunds_cents,as_of=excluded.as_of,
          source=excluded.source,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')''',dict(vals,as_of=as_of,source=source))
        after=_row(db,'gnosis_finance_stripe','singleton',1)
        _audit(db,actor,'stripe_snapshot','stripe',before,after)
        db.commit();return after
    except Exception:db.rollback();raise

def _solana_pubkey(value):
    if value in (None,''):return None
    s=safe_text(value,'Solana public address',32,44)
    if not all(c in B58 for c in s):raise FinanceError('Invalid Solana base58 address')
    number=0
    for c in s:number=number*58+B58.index(c)
    raw=number.to_bytes((number.bit_length()+7)//8,'big')
    raw=b'\x00'*(len(s)-len(s.lstrip('1')))+raw
    if len(raw)!=32:raise FinanceError('Expected 32-byte Solana public key')
    return s

def save_wallet_stub(db,actor,payload):
    address=_solana_pubkey(payload.get('solana_address'))
    mint=_solana_pubkey(payload.get('rstory_mint'))
    db.execute('BEGIN IMMEDIATE')
    try:
        before=_row(db,'gnosis_finance_settings','singleton',1)
        db.execute('UPDATE gnosis_finance_settings SET solana_address=?,rstory_mint=?,updated_at=? WHERE singleton=1',(address,mint,now()))
        after=_row(db,'gnosis_finance_settings','singleton',1)
        _audit(db,actor,'wallet_stub','solana',before,after)
        db.commit();return after
    except Exception:db.rollback();raise
