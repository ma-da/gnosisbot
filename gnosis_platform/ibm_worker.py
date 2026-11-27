"""Operator-invoked IBM Future job handling. Not wired to public routes.

Safety principles:
- Ambiguous submit claims are NEVER automatically resubmitted.
- A complete 128-shot result is fsynced as a checksummed staging file.
- The full result is included in the existing atomic reading+research+ledger transaction.
- Reconciliation after a crash cannot issue a new IBM hardware job.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .ibm_future_queue import claim_next_submission, mark_submitted
from quantum.iching.decoder import analyze_sampler_result

ID_RE = re.compile(r'^[a-f0-9]{32}$')
SHOTS = 128
SEED = 5
BACKENDS = ('ibm_marrakesh', 'ibm_fez')


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _compact(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _path(spool, request_id):
    if not ID_RE.fullmatch(request_id):
        raise ValueError('Invalid request ID')
    return Path(spool).expanduser().resolve() / (request_id + '.json')


def snapshot_compiled(backend_name, *, seed=SEED):
    """Compile the validated circuit and return QPY fingerprint; no submission."""
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_ibm_runtime import QiskitRuntimeService
    from qiskit import qpy
    from quantum.iching.circuit import build_circuit

    if backend_name not in BACKENDS:
        raise ValueError('Backend not in approved allowlist')
    service = QiskitRuntimeService()
    backend = service.backend(backend_name)
    if backend.status().operational is False:
        raise RuntimeError('Backend is not operational')
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3, seed_transpiler=seed)
    compiled = pm.run(build_circuit())
    if compiled.num_clbits != 24 or len(compiled.cregs) != 2:
        raise ValueError('Unexpected compiled classical registers')
    if {r.name: r.size for r in compiled.cregs} != {'coins': 18, 'moves': 6}:
        raise ValueError('Compiled register mapping changed')
    buff = io.BytesIO()
    qpy.dump(compiled, buff)
    digest = hashlib.sha256(buff.getvalue()).hexdigest()
    return service, backend, compiled, digest


def submit_one(db, *, backend_name, enable_live=False):
    """Submit exactly one queued request. Explicit opt-in required.

    An exception AFTER claim leaves status='submitting' and requires operator
    reconciliation because the IBM job may have been accepted remotely.
    """
    if not enable_live or os.getenv('GNOSIS_ENABLE_IBM_LIVE_SUBMISSION') != 'YES':
        raise RuntimeError('IBM live submission disabled (two explicit gates required)')
    # Compile before claiming a durable request. This step does not create a job.
    service, backend, compiled, digest = snapshot_compiled(backend_name)
    claim = claim_next_submission(db)
    if claim is None:
        return None
    from qiskit_ibm_runtime import SamplerV2
    # Do not catch and requeue ambiguous errors.
    job = SamplerV2(mode=backend).run([compiled], shots=SHOTS)
    jid = job.job_id()
    mark_submitted(db, claim['request_id'], external_job_id=jid,
                   backend=backend_name, circuit_sha256=digest,
                   circuit_version='iching_now_becoming_24q_seed5_v1',
                   shots=SHOTS, metadata={'seed': SEED, 'optimization_level': 3,
                                          'selection': 'iching_global_medoid_weighted_lines_v1'})
    return {'request_id': claim['request_id'], 'external_job_id': jid,
            'backend': backend_name, 'circuit_sha256': digest}


def _sufficient_space(directory, required_free_bytes):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    if shutil.disk_usage(directory).free < required_free_bytes:
        raise OSError('Insufficient free disk space for durable IBM result')


def stage_result(db, request_id, *, result, spool, min_free_bytes=1024*1024*1024):
    """Stage a completed SamplerV2 result; this function cannot debit credits.

    Takes a result object as an argument to support mocked tests without IBM.
    Writes a full 128-shot archive to a local JSON file with fsync, then marks
    the job result_ready. Idempotent staging refuses mismatched existing files.
    """
    row = db.execute('SELECT * FROM ibm_future_jobs WHERE request_id=?', (request_id,)).fetchone()
    if not row or row['status'] not in ('submitted', 'running', 'result_ready'):
        raise ValueError('Expected a submitted IBM Future job')
    if row['shots'] != SHOTS or not row['external_job_id'] or not row['circuit_sha256']:
        raise ValueError('Missing committed job provenance')
    from quantum.iching.medoid import canonical_payload
    selection = analyze_sampler_result(result, expected_shots=SHOTS)
    batch = canonical_payload(selection)
    payload = {
        'schema': 'gnosis.ibm_result.v1', 'request_id': request_id,
        'external_job_id': row['external_job_id'], 'backend': row['backend'],
        'circuit_sha256': row['circuit_sha256'], 'circuit_version': row['circuit_version'],
        'submitted_at': row['submitted_at'], 'staged_at': utcnow(),
        'selection': batch,
    }
    directory = Path(spool).expanduser().resolve()
    _sufficient_space(directory, min_free_bytes)
    destination = _path(directory, request_id)
    # Repeated staging must never replace a previously staged shot batch.
    if destination.exists():
        stored = json.loads(destination.read_text(encoding='utf8'))
        if (stored.get('request_id') != request_id or stored.get('external_job_id') != row['external_job_id']
                or stored.get('selection', {}).get('shots') != batch['shots']):
            raise ValueError('Existing staged archive conflicts with IBM result')
    else:
        text = _compact(payload).encode('utf8')
        try:
            with destination.open('xb') as f:
                os.chmod(destination, 0o600)
                f.write(text)
                f.flush(); os.fsync(f.fileno())
            dfd = os.open(directory, os.O_RDONLY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
        except FileExistsError:
            raise ValueError('Concurrent stage conflict; inspect archive') from None
    db.execute('BEGIN IMMEDIATE')
    try:
        current = db.execute('SELECT status,external_job_id FROM ibm_future_jobs WHERE request_id=?',
                             (request_id,)).fetchone()
        if current['external_job_id'] != row['external_job_id']:
            raise ValueError('IBM job changed during staging')
        if current['status'] in ('submitted', 'running'):
            db.execute("UPDATE ibm_future_jobs SET status='result_ready',updated_at=? WHERE request_id=?",
                       (utcnow(), request_id))
        elif current['status'] != 'result_ready':
            raise ValueError('Unexpected job state')
        db.commit()
    except Exception:
        db.rollback(); raise
    return {'request_id': request_id, 'selected_shot_index': batch['selected_shot_index'],
            'shots': SHOTS, 'spool_path': str(destination)}


def retrieve_one(db, request_id, *, spool):
    """Retrieve a known job ID only; never submit. Nonfinal jobs remain pending."""
    service=db.execute('SELECT service_id FROM service_requests WHERE request_id=?',(request_id,)).fetchone()
    if service and service['service_id'].startswith('runes.'):
        from .future_execution import retrieve_rune
        return retrieve_rune(db,request_id)
    row = db.execute('SELECT * FROM ibm_future_jobs WHERE request_id=?', (request_id,)).fetchone()
    if not row or not row['external_job_id'] or row['status'] not in ('submitted', 'running', 'result_ready'):
        raise ValueError('No retrievable IBM job')
    if row['status'] == 'result_ready':
        return {'status': 'result_ready', 'request_id': request_id}
    if json.loads(row['metadata_json'] or '{}').get('trial'):
        from .future_execution import retrieve
        return retrieve(db,request_id,spool)
    from qiskit_ibm_runtime import QiskitRuntimeService
    job = QiskitRuntimeService().job(row['external_job_id'])
    status = str(job.status()).upper()
    if 'DONE' in status or 'COMPLETED' in status:
        return stage_result(db, request_id, result=job.result(), spool=spool)
    # Do not release a lock on a transient status or a string exception.
    if any(flag in status for flag in ('ERROR', 'FAILED', 'CANCELLED')):
        return {'status': 'needs_operator_reconciliation', 'ibm_status': status}
    return {'status': 'pending', 'ibm_status': status}


def _valid_stage(db, request_id, spool):
    path = _path(spool, request_id)
    payload = json.loads(path.read_text(encoding='utf8'))
    row = db.execute('SELECT * FROM ibm_future_jobs WHERE request_id=?', (request_id,)).fetchone()
    if not row or row['status'] not in ('result_ready', 'completed'):
        raise ValueError('IBM job result has not been staged')
    if (payload['schema'] != 'gnosis.ibm_result.v1' or payload['request_id'] != request_id
            or payload['external_job_id'] != row['external_job_id']
            or payload['circuit_sha256'] != row['circuit_sha256']):
        raise ValueError('Staged result provenance mismatch')
    selection = payload['selection']
    from quantum.iching.medoid import select_medoid, canonical_payload
    shots = [{'coin_bits': x['coin_bits'], 'moving_qpu_bits': x['moving_qpu_bits']}
             for x in selection['shots']]
    recomputed = canonical_payload(select_medoid(shots, expected_shots=SHOTS))
    if selection != recomputed:
        raise ValueError('Staged medoid or raw shots failed integrity check')
    return row, payload


def settle_staged(db, request_id, *, spool):
    """One canonical reading and all 128 shots saved before any credit settlement.

    The existing M3C finish_request performs one BEGIN IMMEDIATE transaction
    for result, research projection, and credit settlement. The JSON payload
    includes all shots, so no separately committed raw data are required.
    """
    service_type=db.execute('SELECT service_id FROM service_requests WHERE request_id=?',(request_id,)).fetchone()
    if service_type and service_type['service_id'].startswith('runes.'):
        from .future_execution import settle_rune
        return settle_rune(db,request_id)
    row, payload = _valid_stage(db, request_id, spool)
    service = db.execute('SELECT service_id,status,credits_cost,consultation_id FROM service_requests WHERE request_id=?',
                         (request_id,)).fetchone()
    if not service or service['service_id'] != 'iching.quantum_future' or service['credits_cost'] != 10:
        raise ValueError('Not an authorized 10-credit IBM Future request')
    if service['status'] == 'completed':
        if row['status'] != 'completed':
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute("UPDATE ibm_future_jobs SET status='completed',updated_at=?,finished_at=? WHERE request_id=? AND status='result_ready'",
                           (utcnow(), utcnow(), request_id))
                db.commit()
            except Exception: db.rollback(); raise
        from .reading_completion import wake_for
        wake_for(db)
        return {'status': 'completed', 'replayed': True}
    if service['status'] != 'pending':
        raise ValueError('IBM request no longer pending')
    from .transactions import finish_request
    chosen = payload['selection']['shots'][payload['selection']['selected_shot_index']]
    # All shot material remains in provenance JSON. The research projector also
    # retains that provenance, and only ONE reading_facts row is created.
    reading = {
        'lines': chosen['values'],
        'coin_bits_bottom_to_top': [chosen['coin_bits'][i:i+3] for i in range(0,18,3)],
        'now_yang_bits_bottom_to_top': [v % 2 for v in chosen['values']],
        'becoming_yang_bits_bottom_to_top': [int(v % 2) ^ int(v in (6,9)) for v in chosen['values']],
        'moving_positions_bottom_to_top': chosen['moving_positions_bottom_to_top'],
        'casting_method': 'ibm_128shot_medoid',
    }
    provenance = {
        'provider': 'ibm', 'backend': payload['backend'], 'external_job_id': payload['external_job_id'],
        'circuit_sha256': payload['circuit_sha256'], 'circuit_version': payload['circuit_version'],
        'submitted_at': payload['submitted_at'], 'selection': payload['selection'],
        'selected_shot_index': payload['selection']['selected_shot_index'],
        'n_shots': SHOTS, 'staged_at': payload['staged_at'],
        'source_quality': 'hardware_measurements',
    }
    # This transaction stores the full raw archive, reading and research projection
    # and settles credits together. If this raises, balances remain locked, not debited.
    finish_request(db, request_id, success=True, result_json=reading, provenance_json=provenance)
    # Following a crash, restart can call settle_staged again and mark completed.
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute("UPDATE ibm_future_jobs SET status='completed',updated_at=?,finished_at=? WHERE request_id=? AND status='result_ready'",
                   (utcnow(), utcnow(), request_id))
        db.commit()
    except Exception: db.rollback(); raise
    from .reading_completion import wake_for
    wake_for(db)
    return {'status': 'completed', 'replayed': False,
            'selected_shot_index': payload['selection']['selected_shot_index']}


def capacity_scenarios(*, bytes_per_reading=50_000, days=365):
    """Illustrative uncompressed IBM archive sizing, excludes backups."""
    return {str(rate): {'readings_per_year': rate*days,
                        'annual_gb': round(rate*days*bytes_per_reading/1e9, 3)}
            for rate in (100, 1000, 10000, 100000)}
