"""Trusted synchronous QRNG execution; idempotent claim before network use.

A process crash after the claim can leave a pending request; never retry it by
silently drawing replacement entropy. A recovery tool should mark abandoned
claims failed after operator verification (no credit locked for QCI).
"""
import sqlite3
from uuid import uuid4
from .qci_qrng import cast, QCIError
from .transactions import finish_request
from .identity import iso, now


def run_claimed_qci(db, request):
    """Returns (status, request). Status: completed, in_progress, failed.

    Called after begin_consultation has committed. The claim and its commit
    precede QCI network I/O. One process may execute each consultation.
    """
    if request['status'] != 'pending':
        return request['status'],request
    stamp=iso(now())
    claim=db.execute('''INSERT OR IGNORE INTO provider_requests
        (provider_request_id,request_id,provider,status,created_at,updated_at)
        VALUES(?,?,?,'running',?,?)''',
        (uuid4().hex,request['request_id'],'qci',stamp,stamp))
    claimed=claim.rowcount==1
    db.commit()
    if not claimed:
        return 'in_progress',request
    try:
        reading, provenance=cast()
    except Exception:
        # No result => no settlement; safely fail this zero-cost request.
        result=finish_request(db,request['request_id'],success=False)
        state='failed'
    else:
        # If database persistence fails, do not convert a potentially completed
        # request to a failure: leave its claim for explicit recovery.
        result=finish_request(db,request['request_id'],success=True,
                             result_json=reading,provenance_json=provenance)
        state='completed'
    db.execute('''UPDATE provider_requests SET status=?, updated_at=?
                  WHERE request_id=? AND provider='qci' ''',
               (state,iso(now()),request['request_id']))
    db.commit()
    return state,result
