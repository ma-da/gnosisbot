"""Claim-before-request, fail-closed NIST consultation execution."""
from __future__ import annotations
from uuid import uuid4
from .identity import iso,now
from .transactions import finish_request
from .nist_beacon import cast


def run_claimed_nist(db, request):
    if request['status'] != 'pending':
        return request['status'], request
    stamp = iso(now())
    claim = db.execute('''INSERT OR IGNORE INTO provider_requests
      (provider_request_id,request_id,provider,status,created_at,updated_at)
      VALUES(?,?,?,'running',?,?)''',
      (uuid4().hex,request['request_id'],'nist',stamp,stamp))
    claimed = claim.rowcount == 1
    db.commit()
    if not claimed:
        return 'in_progress',request
    try:
        reading, provenance = cast(request['request_id'])
    except Exception:
        result = finish_request(db,request['request_id'],success=False)
        state = 'failed'
    else:
        # A DB fault after a successful public-pulse fetch must not cause
        # implicit recasting; failed/unknown claims remain visible for review.
        result = finish_request(db,request['request_id'],success=True,
                                result_json=reading,provenance_json=provenance)
        state = 'completed'
    db.execute('''UPDATE provider_requests SET status=?,updated_at=?
                  WHERE request_id=? AND provider='nist' ''',
               (state,iso(now()),request['request_id']))
    db.commit()
    return state,result
