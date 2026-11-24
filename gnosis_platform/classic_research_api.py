"""Consent-only intake for anonymous browser-crypto I Ching casts.

Not a public question feed or a trusted entropy ledger. This route accepts no
account identifier, IP field, browser fingerprint, or personal metadata. A cast
reaches this endpoint only after an explicit unchecked-by-default opt-in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_api import guard_origin
from .db import connect

router = APIRouter(prefix='/api/v1/research', tags=['gnosis-private-research-intake'])


class ClassicResearchSubmission(BaseModel):
    submission_key: str = Field(min_length=32, max_length=36)
    question: str = Field(min_length=1, max_length=2000)
    inquiry_style: Literal['direct', 'meditative'] = 'direct'
    line_values: list[int] = Field(min_length=6, max_length=6)
    research_publication_consent: Literal[True]


def _digest(body: ClassicResearchSubmission) -> str:
    payload = [body.question, body.inquiry_style, body.line_values, True]
    serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


@router.post('/classic-optin', dependencies=[Depends(guard_origin)], status_code=201)
def classic_research_optin(body: ClassicResearchSubmission, request: Request):
    # Browser POSTs send Origin. Reject non-browser or cross-site calls. This
    # endpoint is deliberately anonymous; do not mint sessions or save cookies.
    configured = os.environ.get('GNOSIS_WEB_ORIGIN', 'https://gnosis.bot').rstrip('/')
    if request.headers.get('origin', '').rstrip('/') != configured:
        raise HTTPException(403, 'Browser origin required')
    length = request.headers.get('content-length')
    if length and length.isascii() and length.isdigit() and int(length) > 8192:
        raise HTTPException(413, 'Submission too large')
    if not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', body.submission_key):
        raise HTTPException(422, 'Invalid submission key')
    if not body.question.strip() or any(type(n) is not int or n not in (6, 7, 8, 9) for n in body.line_values):
        raise HTTPException(422, 'Invalid research submission')
    fingerprint = _digest(body)
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec='milliseconds')
    try:
        with closing(connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute(
                'SELECT submission_id,request_hash FROM classic_research_optins WHERE submission_key=?',
                (body.submission_key,)
            ).fetchone()
            if existing:
                if existing['request_hash'] != fingerprint:
                    db.rollback()
                    raise HTTPException(409, 'Submission key already used with different data')
                db.commit()
                return {'recorded': True, 'submission_id': existing['submission_id'], 'classification': 'restricted_review_required'}
            # Bounded global intake, no IP, account, cookie or fingerprint retained.
            minute = (now - timedelta(minutes=1)).isoformat(timespec='milliseconds')
            day = (now - timedelta(days=1)).isoformat(timespec='milliseconds')
            if db.execute('SELECT COUNT(*) FROM classic_research_optins WHERE created_utc>=?', (minute,)).fetchone()[0] >= 30:
                db.rollback()
                raise HTTPException(429, 'Research intake busy, please try again later')
            if db.execute('SELECT COUNT(*) FROM classic_research_optins WHERE created_utc>=?', (day,)).fetchone()[0] >= 1000:
                db.rollback()
                raise HTTPException(429, 'Research intake capacity reached')
            submission_id = uuid4().hex
            db.execute('''INSERT INTO classic_research_optins
              (submission_id, submission_key, request_hash, created_utc,
               question, inquiry_style, line_values_json,
               research_publication_consent, source, verification_status, classification)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
              (submission_id, body.submission_key, fingerprint, stamp,
               body.question, body.inquiry_style, json.dumps(body.line_values),
               1, 'browser_crypto', 'self_reported_client_cast', 'restricted_review_required'))
            db.commit()
    except HTTPException:
        raise
    except Exception:
        # Never reflect raw SQL, secrets, or a submitted question to a client.
        raise HTTPException(503, 'Research intake temporarily unavailable') from None
    return {'recorded': True, 'submission_id': submission_id, 'classification': 'restricted_review_required'}
