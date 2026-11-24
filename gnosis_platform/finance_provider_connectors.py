"""Read-only financial provider balance adapters, with fixed hosts and fail-closed parsing.

No model calls, paid hardware work, payments, or signing. Provider account keys
are read from the protected process environment and are never logged/returned.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

# Do not take API URLs from requests, settings, or database rows.
PROVIDERS = {
    'deepseek': {'env': ('DEEPSEEK_API_KEY',), 'live_balance': True, 'method': 'GET',
                 'description': 'Read-only USD balance from DeepSeek /user/balance'},
    'deepinfra': {'env': ('DEEPINFRA_API_KEY', 'DEEPINFRA_TOKEN'), 'live_balance': True, 'method': 'GET',
                  'description': 'Read-only USD prepaid balance from DeepInfra /payment/checklist'},
    'ankr': {'env': ('ANKR_API_KEY', 'GNOSIS_ANKR_API_KEY'), 'live_balance': False,
             'description': 'Account balance requires separate browser OAuth to Ankr Management MCP; Web3 API key cannot read it'},
    'iqm': {'env': ('IQM_TOKEN', 'IQM_API_TOKEN', 'GNOSIS_IQM_TOKEN'), 'live_balance': False,
            'description': 'Resonance token can authenticate QPU requests; no verified compatible credit-balance API found'},
}
ENDPOINTS = {
    'deepseek': 'https://api.deepseek.com/user/balance',
    'deepinfra': 'https://api.deepinfra.com/payment/checklist?compute_owed=true',
}

class ConnectorError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def credentials(provider, env=None):
    env = os.environ if env is None else env
    if provider not in PROVIDERS:
        raise ConnectorError('unsupported_provider')
    for var in PROVIDERS[provider]['env']:
        value=env.get(var)
        if isinstance(value,str) and value.strip():
            return value.strip()
    return None


def connection_status(env=None):
    return {pid: {'configured':bool(credentials(pid,env)), 'automatic':config['live_balance'],
                  'description':config['description']} for pid,config in PROVIDERS.items()}


def _nonneg_decimal(value):
    if isinstance(value,bool) or value is None or isinstance(value,(list,dict)):
        raise ConnectorError('invalid_balance_data')
    try: n = Decimal(str(value))
    except (InvalidOperation,ValueError): raise ConnectorError('invalid_balance_data')
    if not n.is_finite() or n<0 or n>Decimal('1000000000'):
        raise ConnectorError('invalid_balance_data')
    return n


def _signed_decimal(value):
    if isinstance(value,bool) or value is None or isinstance(value,(list,dict)):
        raise ConnectorError('invalid_balance_data')
    try: n = Decimal(str(value))
    except (InvalidOperation,ValueError): raise ConnectorError('invalid_balance_data')
    if not n.is_finite() or abs(n)>Decimal('1000000000'):
        raise ConnectorError('invalid_balance_data')
    return n


def parse_balance(provider, payload):
    """Return a nonnegative USD balance. Never convert CNY or silently clamp debts."""
    if not isinstance(payload,dict):raise ConnectorError('invalid_balance_data')
    if provider=='deepseek':
        rows=payload.get('balance_infos')
        if not isinstance(rows,list) or not rows:
            raise ConnectorError('invalid_balance_data')
        usd=[r for r in rows if isinstance(r,dict) and r.get('currency')=='USD']
        if len(usd)!=1:
            raise ConnectorError('usd_balance_unavailable')
        value=_nonneg_decimal(usd[0].get('total_balance'))
        return {'usd':str(value), 'source':'DeepSeek official USD balance API',
                'notes':'Total includes prepaid and unexpired granted credits; USD only'}
    if provider=='deepinfra':
        if payload.get('suspended') is True:
            raise ConnectorError('provider_account_suspended')
        # DeepInfra shows prepaid USD as -(stripe_balance + recent).
        # These fields are in USD, not cents. Do not double subtract usage.
        stripe=_signed_decimal(payload.get('stripe_balance'))
        recent=_signed_decimal(payload.get('recent'))
        value=-(stripe+recent)
        if value < 0:
            raise ConnectorError('negative_prepaid_balance_manual_review')
        if value > Decimal('1000000000'):
            raise ConnectorError('invalid_balance_data')
        return {'usd':str(value), 'source':'DeepInfra official prepaid billing checklist',
                'notes':'Prepaid USD including uninvoiced usage; does not include scoped model credits'}
    raise ConnectorError('no_documented_balance_endpoint')


def _get_json(provider, token, opener=None):
    url=ENDPOINTS[provider]
    req=Request(url, headers={'Authorization':'Bearer '+token, 'Accept':'application/json',
                              'User-Agent':'GnosisFinancials/1.0'}, method='GET')
    client = opener if opener is not None else build_opener(_NoRedirect())
    try:
        with client.open(req, timeout=12) as res:
            if res.status != 200:raise ConnectorError('unexpected_http_status')
            raw=res.read(32769)
            if len(raw)>32768:raise ConnectorError('oversize_response')
    except HTTPError as err:
        # Hide server message/body and request headers containing secrets.
        raise ConnectorError('provider_http_'+str(err.code)) from None
    except (URLError,TimeoutError,OSError):
        raise ConnectorError('provider_connection_failed') from None
    try:
        payload=json.loads(raw)
    except (ValueError,UnicodeError):
        raise ConnectorError('invalid_provider_response') from None
    return payload


def refresh(provider, env=None, opener=None):
    if provider not in PROVIDERS:raise ConnectorError('unsupported_provider')
    if not PROVIDERS[provider]['live_balance']:
        raise ConnectorError('no_documented_balance_endpoint')
    token=credentials(provider,env)
    if not token:raise ConnectorError('credential_not_configured')
    data=parse_balance(provider,_get_json(provider,token,opener))
    return {
        'provider_id':provider,
        'name':'DeepSeek' if provider=='deepseek' else 'DeepInfra',
        'units':'USD','quantity':data['usd'],'rate_usd':'1','state':'reported',
        'source':data['source'],
        'observed_at':datetime.now(timezone.utc).date().isoformat(),
        'notes':data['notes'],
    }
