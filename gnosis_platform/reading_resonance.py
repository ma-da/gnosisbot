"""Owner-only subjective feedback, independent of settlement and GQTP."""
from contextlib import closing
from datetime import datetime, timezone
import re
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StrictBool
from .auth_api import authenticated, guard_origin
from .db import connect

router = APIRouter(tags=['gnosis-reading-resonance'])

class ResonanceInput(BaseModel):
    resonated: StrictBool
    class Config:
        extra = 'forbid'


def state(row):
    if row is None:
        return {'resonated': False, 'recorded': False, 'updated_at': None}
    return {'resonated': bool(row['resonated']), 'recorded': True,
            'updated_at': row['updated_at']}


def attach_to_activity(db, items):
    ids = [i['consultation_id'] for i in items if i['status'] == 'completed']
    if not ids:
        return
    # items come only from the authenticated account hub's owner-filtered query.
    marks = ','.join('?' for _ in ids)
    rows = db.execute(f'''SELECT r.consultation_id AS cid, f.resonated, f.updated_at
        FROM reading_results r LEFT JOIN reading_resonance f USING(consultation_id)
        WHERE r.consultation_id IN ({marks})''', ids).fetchall()
    lookup = {r['cid']: state(r if r['resonated'] is not None else None) for r in rows}
    for i in items:
        if i['consultation_id'] in lookup:
            i['resonance'] = lookup[i['consultation_id']]


def set_resonance(db, *, account_id, consultation_id, resonated):
    if not re.fullmatch('[0-9a-f]{32}', consultation_id):
        raise HTTPException(404, 'Reading not found')
    if type(resonated) is not bool:
        raise ValueError('Boolean required')
    db.execute('BEGIN IMMEDIATE')
    try:
        exists = db.execute('''SELECT 1 FROM consultations c JOIN reading_results r USING(consultation_id)
            WHERE c.consultation_id=? AND c.account_id=? AND c.status='completed' ''',
            (consultation_id, account_id)).fetchone()
        if not exists:
            raise HTTPException(404, 'Reading not found')
        stamp = datetime.now(timezone.utc).isoformat()
        # Idempotent desired-state assignment: repeated identical requests don't change timestamps.
        # An initial false is a no-op, not evidence of a negative evaluation.
        if resonated:
            db.execute('''INSERT INTO reading_resonance VALUES(?,1,?,?)
                ON CONFLICT(consultation_id) DO UPDATE SET resonated=1,updated_at=excluded.updated_at
                WHERE reading_resonance.resonated<>1''', (consultation_id, stamp, stamp))
        else:
            db.execute('''UPDATE reading_resonance SET resonated=0,updated_at=?
                WHERE consultation_id=? AND resonated=1''', (stamp, consultation_id))
        result = state(db.execute('SELECT * FROM reading_resonance WHERE consultation_id=?',
                                  (consultation_id,)).fetchone())
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


@router.put('/readings/{consultation_id}/resonance', dependencies=[Depends(guard_origin)])
def update_resonance(consultation_id: str, body: ResonanceInput, response: Response,
                     user: dict = Depends(authenticated)):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex'
    with closing(connect()) as db:
        return set_resonance(db, account_id=user['account_id'], consultation_id=consultation_id,
                             resonated=body.resonated)
