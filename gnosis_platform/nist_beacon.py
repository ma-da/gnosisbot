"""NIST Beacon 2.0 public, reproducible I Ching casts.

One latest PUBLIC beacon pulse may serve multiple consultations. SHAKE256 with a
server-assigned request ID domain-separates them. This is deterministic public
post-processing, NOT new per-user hardware entropy or a private RNG.

This adapter validates transport, structure, pulse status and freshness, but does
NOT independently validate NIST's digital-signature certificate chain.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from .qci_qrng import reading_from_bits

URL = 'https://beacon.nist.gov/beacon/2.0/pulse/last'
_HEX_512 = re.compile(r'^[0-9a-fA-F]{128}$')
_HEX_ID = re.compile(r'^[0-9a-f]{32}$')

class NISTError(RuntimeError):
    pass


def parse_and_cast(payload, request_id, *, current_time=None, max_age_seconds=180):
    """Validate a pulse and derive exactly 18 reproducible coin bits."""
    if not isinstance(payload, dict) or not isinstance(payload.get('pulse'), dict):
        raise NISTError('Missing NIST pulse object')
    pulse = payload['pulse']
    if not _HEX_ID.fullmatch(request_id or ''):
        raise NISTError('Invalid server-generated consultation request ID')
    if (pulse.get('version') != '2.0' or type(pulse.get('statusCode')) is not int
            or pulse['statusCode'] != 0):
        raise NISTError('Unusable NIST pulse version or status')
    for k in ('chainIndex', 'pulseIndex'):
        if type(pulse.get(k)) is not int or pulse[k] < 1:
            raise NISTError('Invalid NIST chain or pulse index')
    output = pulse.get('outputValue')
    if not isinstance(output, str) or not _HEX_512.fullmatch(output):
        raise NISTError('NIST pulse output must be 512-bit hexadecimal')
    ts = pulse.get('timeStamp')
    if not isinstance(ts, str):
        raise NISTError('NIST timestamp missing')
    try:
        published = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except ValueError as e:
        raise NISTError('Invalid NIST timestamp') from e
    if published.tzinfo is None:
        raise NISTError('NIST timestamp must have a timezone')
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('current_time must be timezone-aware')
    age = (now - published).total_seconds()
    if not (-30 <= age <= max_age_seconds):
        raise NISTError('Stale or future-dated NIST pulse')
    for k in ('certificateId', 'signatureValue'):
        val = pulse.get(k)
        if not isinstance(val, str) or not val or re.fullmatch('[0-9a-fA-F]+', val) is None:
            raise NISTError('Missing NIST signature/certificate metadata')
    # Domain separation and request ID are public, replayable inputs. No fallback RNG.
    domain = b'gnosis.iching.nist-beacon-v2.shake256.v1\x00'
    digest = hashlib.shake_256(domain + bytes.fromhex(output)
                               + bytes.fromhex(request_id)).digest(3)
    bits = [(digest[i // 8] >> (7 - i % 8)) & 1 for i in range(18)]
    reading = reading_from_bits(bits)
    provenance = {
        'provider': 'nist', 'service': 'public_randomness_beacon_v2',
        'endpoint': URL, 'beacon_chain': pulse['chainIndex'],
        'beacon_pulse': pulse['pulseIndex'], 'beacon_timestamp': ts,
        'beacon_output_value': output.upper(),
        'beacon_certificate_id': pulse['certificateId'],
        'beacon_signature_value': pulse['signatureValue'],
        'signature_verified_locally': False,
        'public_beacon': True,
        'independent_entropy_per_consultation': False,
        'derivation': 'SHAKE256(domain || 512-bit NIST outputValue || 128-bit server request ID), first 18 MSB-first bits',
        'derivation_version': 'gnosis-nist-shake256-v1',
        'derivation_request_id': request_id,
        'distribution': 'public_beacon_deterministically_personalized',
        'n_samples': 18, 'n_bits': 1,
        'entropy_sha256': hashlib.sha256(bytes(bits)).hexdigest(),
        'conversion': 'three derived bits per line, values=6+sum(bits), bottom first',
        'cast_utc': now.astimezone(timezone.utc).isoformat(),
        'pulse_age_seconds': round(age, 2),
        'fallback_used': False,
    }
    return reading, provenance


def cast(request_id, *, opener=None, current_time=None):
    started = time.perf_counter()
    request = Request(URL, headers={
        'Accept': 'application/json',
        'User-Agent': 'GnosisBot/1.0 (+https://gnosis.bot)',
        'Cache-Control': 'no-cache',
    }, method='GET')
    try:
        with (opener or urlopen)(request, timeout=12) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise NISTError('Oversized NIST response')
        payload = json.loads(raw)
        reading, provenance = parse_and_cast(payload, request_id,
                                              current_time=current_time)
    except NISTError:
        raise
    except Exception:
        raise NISTError('NIST Beacon unavailable or returned invalid data') from None
    provenance['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
    return reading, provenance
