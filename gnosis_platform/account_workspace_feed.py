"""Read-only, opt-in RentAHuman public listing adapter for the account workspace.

No credentials, writes, applications, payments or escrow claims. Remote status is
provider-reported; the adapter never asserts independent funding verification.
Enable with GNOSIS_ENABLE_ROBOT_WORK_FEED=YES after validating the remote payload.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, Response
from .auth_api import authenticated

router = APIRouter(prefix='/api/v1/accounts/workspace', tags=['gnosis-workspace'])
_SCHEMA = 'gnosis.workspace-robot-bounties.v1'
_URL = 'https://rentahuman.ai/api/bounties?status=open&isRemoteOnly=true&sort=new&limit=80'
_LOCK = threading.Lock()
_CACHE = {'until': 0.0, 'data': None}


def _parse_date(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except ValueError:
        return None


def _normalize(payload: object, now: datetime | None = None) -> list[dict]:
    """Return only recent, open, properly identified public remote listings."""
    now = now or datetime.now(timezone.utc)
    if isinstance(payload, dict):
        entries = payload.get('bounties', payload.get('data', payload.get('items')))
    else:
        entries = payload
    if isinstance(entries, dict):
        entries = entries.get('bounties', entries.get('items'))
    if not isinstance(entries, list):
        return []
    result = []
    seen = set()
    for entry in entries[:100]:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get('id') or entry.get('_id')
        if (not isinstance(identifier, str) or not (3 <= len(identifier) <= 100)
                or not all(c.isascii() and (c.isalnum() or c in '-_') for c in identifier)
                or identifier in seen):
            continue
        if entry.get('status') not in (None, 'open'):
            continue
        if entry.get('isFunded') is False or entry.get('funded') is False:
            continue
        funding = entry.get('fundingStatus', entry.get('funding_status'))
        if isinstance(funding, str) and funding.lower() in ('unfunded','pending','pending_deposit','failed','cancelled'):
            continue
        # API-side isRemoteOnly is authoritative, but reject explicit contrary metadata.
        if entry.get('isRemote') is False or entry.get('isRemoteAllowed') is False:
            continue
        location = entry.get('location')
        if isinstance(location, dict) and location.get('isRemoteAllowed') is False:
            continue
        title = entry.get('title')
        if not isinstance(title, str) or not title.strip():
            continue
        posted = _parse_date(entry.get('publishedAt') or entry.get('createdAt') or entry.get('created_at'))
        if posted is None or posted > now + timedelta(minutes=5) or posted < now - timedelta(days=14):
            continue
        price = entry.get('price')
        pay = entry.get('pay')
        if not isinstance(price, (int, float)) and isinstance(pay, dict):
            price = pay.get('price')
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            continue
        price_type = entry.get('priceType') or (pay.get('priceType') if isinstance(pay, dict) else None)
        price_type = price_type if price_type in ('fixed', 'hourly') else 'fixed'
        age_days = max(0, (now - posted).days)
        seen.add(identifier)
        result.append({'id': identifier, 'title': title.strip()[:140],
                       'reward_display': f'${price:,.2f}' + ('/hr' if price_type == 'hourly' else ' fixed'),
                       'age_display': 'Today' if age_days == 0 else f'{age_days}d ago',
                       '_value': float(price)})
    result.sort(key=lambda x: x['_value'], reverse=True)
    for item in result:
        del item['_value']
    return result[:4]


def _load_live() -> dict:
    # GNOSIS ACCOUNT LAYOUT V0.3.2: optional key, server-side only.
    headers = {'User-Agent':'GnosisBot-Workspace/0.3.2', 'Accept':'application/json'}
    key = os.getenv('RENTAHUMAN_API_KEY', '').strip()
    if key:
        if not re.fullmatch(r'[A-Za-z0-9_.-]{8,256}', key):
            raise ValueError('invalid external API key configuration')
        headers['X-API-Key'] = key
    request = Request(_URL, headers=headers)
    with urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise ValueError('remote response unsuccessful')
        body = response.read(300001)
        if len(body) > 300000:
            raise ValueError('remote response too large')
    payload = json.loads(body)
    if not isinstance(payload, (dict, list)):
        raise ValueError('unexpected response format')
    if isinstance(payload, dict) and payload.get('success') is False:
        raise ValueError('remote request rejected')
    return {'schema': _SCHEMA, 'status': 'ok', 'items': _normalize(payload),
            'source': 'RentAHuman public bounties'}


@router.get('/robot-work')
def robot_work(response: Response, _account: dict = Depends(authenticated)) -> dict:
    response.headers['Cache-Control'] = 'private, no-store'
    if os.getenv('GNOSIS_ENABLE_ROBOT_WORK_FEED') != 'YES':
        return {'schema': _SCHEMA, 'status': 'disabled', 'items': []}
    with _LOCK:
        if _CACHE['data'] is not None and _CACHE['until'] > time.monotonic():
            return _CACHE['data']
        try:
            data = _load_live()
            ttl = 20 * 60
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            data = {'schema': _SCHEMA, 'status': 'unavailable', 'items': []}
            ttl = 90
        _CACHE.update(until=time.monotonic() + ttl, data=data)
        return data
