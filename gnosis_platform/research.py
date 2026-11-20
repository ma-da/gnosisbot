"""M3C reproducible projections. Immutable reading_results remains authoritative.

Backfills pre-M3C completions, retains provider raw samples only when truly available,
and deliberately refuses inconsistent coin-bit / line combinations.
"""
from __future__ import annotations
import hashlib
import json
from uuid import uuid4

VERSION = 'gnosis.research.v1'


def _compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _mask(bits):
    if not isinstance(bits, list) or len(bits) != 6 or any(type(b) is not int or b not in (0,1) for b in bits):
        raise ValueError('Invalid six-line bit array')
    return sum(value << position for position, value in enumerate(bits))


def project_completed(db, consultation_id, reading, provenance, completed_at=None):
    """Insert two research projections in CALLER transaction; no commit here.

    Fail closed on malformed records. Replays are no-ops. Does not store credentials.
    """
    row = db.execute('SELECT account_id,application_id,finished_at FROM consultations WHERE consultation_id=?',
                     (consultation_id,)).fetchone()
    if not row or not row['account_id']:
        raise ValueError('Consultation missing account owner')
    if not isinstance(provenance,dict) or not provenance:
        raise ValueError('Missing provenance')
    lines = reading.get('lines') if isinstance(reading,dict) else None
    if not isinstance(lines,list) or len(lines)!=6 or any(type(v) is not int or v not in (6,7,8,9) for v in lines):
        raise ValueError('Invalid line values')
    now = [v%2 for v in lines]
    relating = [((v%2) ^ (v in (6,9))) for v in lines]
    moving = [int(v in (6,9)) for v in lines]
    # Verify the stored deterministic interpretation, when present.
    for key, expected in [('now_yang_bits_bottom_to_top',now),
                          ('becoming_yang_bits_bottom_to_top',relating)]:
        if key in reading and reading[key] != expected:
            raise ValueError('Stored line/hexagram mismatch: '+key)
    if 'moving_positions_bottom_to_top' in reading:
        if reading['moving_positions_bottom_to_top'] != [i+1 for i,b in enumerate(moving) if b]:
            raise ValueError('Stored moving lines mismatch')
    coins=reading.get('coin_bits_bottom_to_top')
    if coins is not None:
        if not isinstance(coins,list) or len(coins)!=6 or any(not isinstance(c,str) or len(c)!=3 or set(c)-{'0','1'} for c in coins):
            raise ValueError('Invalid coin-bit record')
        if any(6+c.count('1')!=v for c,v in zip(coins,lines)):
            raise ValueError('Coin bits do not match line values')
    source = provenance.get('provider') or provenance.get('source') or 'unknown'
    if not isinstance(source,str) or len(source)>80:
        raise ValueError('Invalid source identifier')
    raw = provenance.get('raw_samples_decimal')
    if raw is not None:
        nbits = provenance.get('n_bits')
        nsamples = provenance.get('n_samples')
        if (not isinstance(raw,list) or type(nbits) is not int or not 8<=nbits<=32 or
            type(nsamples) is not int or len(raw)!=nsamples or
            any(type(n) is not int or n<0 or n >= (1<<nbits) for n in raw)):
            raise ValueError('Invalid retained raw sample metadata')
        status='raw_retained'
        raw_json=_compact(raw)
    elif source == 'ibm' and isinstance(provenance.get('selection'), dict):
        # One canonical medoid per consultation, but preserve all 128 raw shots
        # in reading_measurements for source-quality analysis and replay.
        from quantum.iching.medoid import select_medoid, canonical_payload
        selection = provenance['selection']
        shots = selection.get('shots')
        if not isinstance(shots, list) or len(shots) != 128:
            raise ValueError('IBM result missing complete 128-shot archive')
        rebuilt = canonical_payload(select_medoid([
            {'coin_bits': s.get('coin_bits'), 'moving_qpu_bits': s.get('moving_qpu_bits')}
            for s in shots
        ], expected_shots=128))
        if rebuilt != selection or selection['shots'][selection['selected_shot_index']]['values'] != lines:
            raise ValueError('IBM medoid archive does not reproduce saved reading')
        raw_json = _compact({'shots': shots})
        status = 'raw_retained'
    elif coins is not None:
        status='derived_bits_only'
        raw_json=None
    else:
        status='metadata_only'
        raw_json=None
    # Important: SHA of captured raw JSON is distinct from any earlier provider entropy hash.
    raw_hash=hashlib.sha256(raw_json.encode()).hexdigest() if raw_json is not None else None
    # Explicit stable pseudonymous identifier; not a reversible public account fingerprint.
    # Internally joined to account_id; public releases must never emit account_id.
    subject = hashlib.sha256(('gnosis-research-v1:'+row['account_id']).encode()).hexdigest()
    instant=completed_at or row['finished_at']
    if not instant:
        raise ValueError('Completion time is missing')
    if db.execute('SELECT 1 FROM reading_facts WHERE consultation_id=?',(consultation_id,)).fetchone():
        return False
    measurement_id=uuid4().hex
    db.execute('''INSERT INTO reading_measurements
      (measurement_id,consultation_id,source_id,measurement_status,raw_payload_json,
       raw_payload_sha256,provider_metadata_json,sample_count,bits_per_sample,recorded_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)''',
      (measurement_id,consultation_id,source,status,raw_json,raw_hash,
       _compact(provenance),provenance.get('n_samples', provenance.get('n_shots')),provenance.get('n_bits', 24 if source == 'ibm' and status == 'raw_retained' else None),instant))
    db.execute('''INSERT INTO reading_facts
      (consultation_id,account_id,research_subject_id,application_id,source_id,
       primary_mask,relating_mask,moving_mask,moving_count,line_values_json,
       completed_at,measurement_id)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
      (consultation_id,row['account_id'],subject,row['application_id'],source,
       _mask(now),_mask([int(v) for v in relating]),_mask(moving),sum(moving),
       _compact(lines),instant,measurement_id))
    return True


def backfill(db):
    """Backfill all successful readings atomically, raising on inconsistency.

    Call from CLI after migration. Existing records are never overwritten.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        rows=db.execute('''SELECT c.consultation_id,c.finished_at,r.reading_json,r.provenance_json
          FROM reading_results r JOIN consultations c ON c.consultation_id=r.consultation_id
          WHERE c.status='completed' AND c.application_id='iching' AND NOT EXISTS
          (SELECT 1 FROM reading_facts f WHERE f.consultation_id=c.consultation_id)
          ORDER BY c.created_at,c.consultation_id''').fetchall()
        done=0
        for row in rows:
            done+=int(project_completed(db,row['consultation_id'],json.loads(row['reading_json']),
                          json.loads(row['provenance_json']),row['finished_at']))
        db.commit()
        return done
    except Exception:
        db.rollback()
        raise
