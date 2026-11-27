"""Durable IBM Future submission-state registry (M4A; no IBM network operations).

A request already reserved by the credit engine is inserted into this local
queue at most once. Submission claims are NOT automatically retried because a
QPU job may have been accepted before a network response was lost.
"""
from __future__ import annotations
import json
from datetime import datetime,timezone


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def queue_request(db, request_id):
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('''SELECT r.request_id,r.service_id,r.status,r.credits_cost
           FROM service_requests r WHERE r.request_id=?''',(request_id,)).fetchone()
        if not row or row['service_id']!='iching.quantum_future' or row['status']!='pending' or row['credits_cost']!=10:
            raise ValueError('Only pending, 10-credit IBM Future requests may be queued')
        db.execute('''INSERT OR IGNORE INTO ibm_future_jobs(request_id,status,created_at,updated_at)
          VALUES(?,'queued',?,?)''',(request_id,stamp(),stamp()))
        result=dict(db.execute('SELECT * FROM ibm_future_jobs WHERE request_id=?',(request_id,)).fetchone())
        db.commit();return result
    except Exception:
        db.rollback();raise


def claim_next_submission(db):
    """Claim exactly one queued row; concurrency serialized by BEGIN IMMEDIATE.

    A claimed submission is sticky until operator reconciliation. This avoids
    accidental duplicate paid IBM submissions after a crash.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('''SELECT j.request_id FROM ibm_future_jobs j JOIN service_requests r USING(request_id) WHERE j.status='queued' AND r.service_id='iching.quantum_future' AND COALESCE(json_extract(j.metadata_json,'$.controlled_trial'),0)=0
          ORDER BY created_at,request_id LIMIT 1''').fetchone()
        if not row:
            db.commit();return None
        when=stamp()
        db.execute('''UPDATE ibm_future_jobs SET status='submitting',
           submit_claimed_at=?,updated_at=? WHERE request_id=? AND status='queued' ''',
           (when,when,row['request_id']))
        result=dict(db.execute('SELECT * FROM ibm_future_jobs WHERE request_id=?',(row['request_id'],)).fetchone())
        db.commit();return result
    except Exception:
        db.rollback();raise


def mark_submitted(db,request_id,*,external_job_id,backend,circuit_sha256,circuit_version,shots,metadata=None):
    """Record an accepted IBM job; no credit debit occurs here."""
    if not isinstance(external_job_id,str) or not external_job_id.strip():raise ValueError('Job ID required')
    if not isinstance(backend,str) or not backend.startswith('ibm_'):raise ValueError('IBM backend required')
    if not isinstance(circuit_sha256,str) or len(circuit_sha256)!=64 or any(c not in '0123456789abcdef' for c in circuit_sha256):
        raise ValueError('Circuit SHA256 required')
    if type(shots) is not int or shots<=0:raise ValueError('Positive shots required')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT status FROM ibm_future_jobs WHERE request_id=?',(request_id,)).fetchone()
        if not row or row['status']!='submitting':raise ValueError('Job must be claimed before submission')
        now=stamp()
        db.execute('''UPDATE ibm_future_jobs SET status='submitted',backend=?,external_job_id=?,
          circuit_sha256=?,circuit_version=?,shots=?,submitted_at=?,updated_at=?,metadata_json=?
          WHERE request_id=?''',(backend,external_job_id,circuit_sha256,circuit_version,shots,
              now,now,json.dumps(metadata or {},sort_keys=True),request_id))
        db.commit()
    except Exception:
        db.rollback();raise


def list_needing_reconciliation(db):
    rows=db.execute('''SELECT * FROM ibm_future_jobs WHERE status IN
        ('submitting','submitted','running','result_ready','needs_reconciliation')
        ORDER BY created_at,request_id''').fetchall()
    return [dict(r) for r in rows]
