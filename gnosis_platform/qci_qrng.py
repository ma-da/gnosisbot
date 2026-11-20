"""QCI uQRNG adapter. Exactly 18 unbiased independent 1-bit samples per I Ching cast.

Never silently substitute PRNG; network errors fail closed. The server-side QCI
refresh credential is never returned, persisted in consultation results, or logged.
"""
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HOST = 'https://api.qci-prod.com'
_AUTH = '/auth/v1/access-tokens'
_RANDOM = '/qrng/random_numbers'
_LOCK = threading.Lock()
_TOKEN = None
_TOKEN_VALID_UNTIL = 0.0

class QCIError(RuntimeError):
    pass


def _post(path, payload, *, bearer=None, timeout=10):
    body=json.dumps(payload,separators=(',',':')).encode('utf-8')
    headers={'Accept':'application/json','Content-Type':'application/json'}
    if bearer:
        headers['Authorization']='Bearer '+bearer
    request=urllib.request.Request(HOST+path,body,headers,method='POST')
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            data=response.read(256_000)
            return json.loads(data)
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ValueError) as exc:
        # Avoid including error body / URL with secrets; no token in errors.
        raise QCIError('QCI request failed or returned invalid JSON') from None


def _access_token():
    global _TOKEN,_TOKEN_VALID_UNTIL
    if _TOKEN and time.monotonic()<_TOKEN_VALID_UNTIL:
        return _TOKEN
    with _LOCK:
        if _TOKEN and time.monotonic()<_TOKEN_VALID_UNTIL:
            return _TOKEN
        credential=os.environ.get('QCI_API_TOKEN','').strip()
        if not credential:
            raise QCIError('QCI_API_TOKEN is not configured')
        response=_post(_AUTH,{'refresh_token':credential})
        token=response.get('access_token') if isinstance(response,dict) else None
        if not isinstance(token,str) or not token:
            raise QCIError('QCI authentication did not return an access token')
        # Conservative five-minute caching; no JWT decode or trust in ambiguous expires_in.
        _TOKEN=token
        _TOKEN_VALID_UNTIL=time.monotonic()+300
        return token


def _parse_bits(response):
    # QCI's published output is an array of decimal numbers. Avoid accepting
    # booleans, floats, strings, truncated arrays, or transformed sample data.
    if not isinstance(response,list) or len(response)!=18:
        raise QCIError('QCI response must contain exactly 18 quantum samples')
    if any(type(n) is not int or n not in (0,1) for n in response):
        raise QCIError('QCI returned invalid one-bit samples')
    return response


def reading_from_bits(bits):
    """Three coins per line, bottom to top. 0=tails (2), 1=heads (3).

    6 (old yin) p=1/8, 7 p=3/8, 8 p=3/8, 9 (old yang) p=1/8.
    """
    bits=_parse_bits(bits)
    lines=[6+sum(bits[i:i+3]) for i in range(0,18,3)]
    now=[int(v%2==1) for v in lines]
    becoming=[int((v%2==1) ^ (v in (6,9))) for v in lines]
    moving=[i+1 for i,v in enumerate(lines) if v in (6,9)]
    return {
        'lines':lines,
        'coin_bits_bottom_to_top':[''.join(map(str,bits[i:i+3])) for i in range(0,18,3)],
        'now_yang_bits_bottom_to_top':now,
        'becoming_yang_bits_bottom_to_top':becoming,
        'moving_positions_bottom_to_top':moving,
        'casting_method':'three_coins',
    }


def cast():
    started=time.perf_counter()
    token=_access_token()
    response=_post(_RANDOM,{
        'distribution':'uniform_discrete',
        'output_type':'decimal',
        'n_samples':2,
        'n_bits':16,
    },bearer=token)
    # QCI requires at least 8 bits per sample.
    # Two confirmed-supported 16-bit samples supply 32 bits.
    # Use exactly 18 for six traditional three-coin lines.
    if (
        not isinstance(response, list)
        or len(response) != 2
        or any(
            type(n) is not int or not 0 <= n < 65536
            for n in response
        )
    ):
        raise QCIError("Invalid QCI 16-bit sample response")

    bitstream = ''.join(format(n, '016b') for n in response)
    bits = [int(bit) for bit in bitstream[:18]]
    reading = reading_from_bits(bits)
    provenance={
        'provider':'qci',
        'service':'uqrng',
        'endpoint':'/qrng/random_numbers',
        'distribution':'uniform_discrete',
        'n_samples':2,
        'n_bits':16,
        'output_type':'decimal',
        'cast_utc':datetime.now(timezone.utc).isoformat(),
        'latency_ms':round((time.perf_counter()-started)*1000,2),
        'entropy_sha256':hashlib.sha256(bytes(bits)).hexdigest(),
        'conversion':'first 18 bits of two 16-bit QCI samples, MSB first; three coins per line, bottom first',
        'fallback_used':False,
        'raw_samples_decimal':response,
    }
    return reading,provenance
