"""IBM Past: finite, approved, one-time hardware inventory delivered atomically.

Does not contact IBM or create QPU jobs. Each approved archived sample is consumed
exactly once, and is saved with provenance plus its own five-credit settlement.
"""
from __future__ import annotations
import json
from uuid import uuid4
from .identity import iso, now
from .ibm_inventory import coin_reading
from .transactions import _get_request, _record_ledger, TransactionError
from .research import project_completed

SERVICE = 'iching.quantum_past'


def available_count(db):
    return db.execute('''SELECT count(*) FROM ibm_inventory_items i
        JOIN ibm_inventory_batches b ON b.batch_id=i.batch_id
        WHERE i.state='available' AND b.status='approved' ''').fetchone()[0]


def _compact(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def deliver_pending(db, request_id):
    """Deliver a pending request or safely fail/refund if out of stock.

    Credit debit, immutable result, research fact and inventory consumption are
    committed as ONE SQLite transaction. Existing completed requests replay
    without allocating new inventory or charging again.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        req = _get_request(db, request_id)
        if not req or req['service_id'] != SERVICE or req['credits_cost'] != 5:
            raise TransactionError('Not a five-credit IBM Past request')
        if req['status'] == 'completed':
            db.commit()
            return {'status':'completed', 'replayed':True,
                    'consultation_id':req['consultation_id']}
        if req['status'] != 'pending':
            db.commit()
            return {'status': req['status'], 'replayed':True,
                    'consultation_id':req['consultation_id']}
        if req['reserved'] < 5:
            raise TransactionError('Insufficient reserved credits for IBM Past')
        cid = req['consultation_id']
        # The same request recovers its previously held sample after a crash.
        item = db.execute('''SELECT i.*, b.backend,b.external_job_id,b.circuit_sha256,
            b.circuit_version,b.acquired_at,b.submitted_at,b.source_file_sha256,
            b.approved_at,b.approved_by,b.status AS batch_status
            FROM ibm_inventory_items i JOIN ibm_inventory_batches b ON b.batch_id=i.batch_id
            WHERE i.consultation_id=?''',(cid,)).fetchone()
        if item is None:
            item = db.execute('''SELECT i.*, b.backend,b.external_job_id,b.circuit_sha256,
                b.circuit_version,b.acquired_at,b.submitted_at,b.source_file_sha256,
                b.approved_at,b.approved_by,b.status AS batch_status
                FROM ibm_inventory_items i JOIN ibm_inventory_batches b ON b.batch_id=i.batch_id
                WHERE i.state='available' AND b.status='approved'
                ORDER BY b.acquired_at,i.batch_id,i.sample_index LIMIT 1''').fetchone()
            if item:
                db.execute('''UPDATE ibm_inventory_items SET state='held',consultation_id=?,held_at=?
                    WHERE item_id=? AND state='available' ''', (cid,iso(now()),item['item_id']))
        if item is None:
            # A concurrent purchase used the final sample. Release the held
            # five credits in this SAME transaction rather than leave a lock.
            stamp = iso(now())
            db.execute('UPDATE credit_accounts SET available=available+5,reserved=reserved-5 WHERE account_id=?',
                       (req['account_id'],))
            _record_ledger(db,req['account_id'],'release',5,-5,'release:'+request_id,cid)
            db.execute('DELETE FROM cooldowns WHERE account_id=? AND cooldown_scope=? AND next_eligible_at=?',
                       (req['account_id'], 'consultation',req['cooldown_until']))
            db.execute('UPDATE consultations SET status=\'failed\',finished_at=? WHERE consultation_id=?',(stamp,cid))
            db.execute('UPDATE service_requests SET status=\'failed\',completed_at=? WHERE request_id=?',(stamp,request_id))
            db.commit()
            return {'status':'out_of_stock','replayed':False,'consultation_id':cid}
        if item['state'] not in ('available','held') or (item['consultation_id'] not in (None,cid)):
            raise TransactionError('Sample already assigned elsewhere')
        if item['batch_status'] != 'approved':
            raise TransactionError('Archived sample batch is not approved')
        stamp = iso(now())
        reading = coin_reading(item['coin_bits'])
        reading['casting_method']='ibm_archived_three_coin_qpu'
        if item['moving_qpu_bits'] is not None:
            flags=item['moving_qpu_bits']
            reading['moving_qpu_bits_bottom_to_top']=flags
            canonical=''.join('1' if v in (6,9) else '0' for v in reading['lines'])
            reading['moving_flag_matches']=sum(a==b for a,b in zip(canonical,flags))
        provenance = {
            'provider':'ibm_inventory',
            'source_quality':'operator_reviewed_hardware_archive',
            'backend':item['backend'],
            'external_job_id':item['external_job_id'],
            'circuit_sha256':item['circuit_sha256'],
            'circuit_version':item['circuit_version'],
            'submitted_at':item['submitted_at'],
            'acquired_at':item['acquired_at'],
            'batch_id':item['batch_id'],
            'item_id':item['item_id'],
            'sample_index':item['sample_index'],
            'source_file_sha256':item['source_file_sha256'],
            'source_record_sha256':item['source_record_sha256'],
            'measured_flags_present':item['moving_qpu_bits'] is not None,
            'approved_at':item['approved_at'],
            'readings_per_consultation':1,
            'sample_selection':'first_unused_approved_hardware_sample_v1',
            'replay_has_full_128_shot_batch':False,
        }
        db.execute('UPDATE credit_accounts SET reserved=reserved-5 WHERE account_id=?',(req['account_id'],))
        _record_ledger(db,req['account_id'],'settle',0,-5,'settle:'+request_id,cid)
        db.execute('''INSERT INTO reading_results(result_id,consultation_id,schema_version,
            reading_json,provenance_json,created_at) VALUES(?,?,?,?,?,?)''',
            (uuid4().hex,cid,'gnosis.reading.v1',_compact(reading),_compact(provenance),stamp))
        db.execute('UPDATE consultations SET status=\'completed\',finished_at=? WHERE consultation_id=?',(stamp,cid))
        db.execute('UPDATE service_requests SET status=\'completed\',completed_at=? WHERE request_id=?',(stamp,request_id))
        project_completed(db,cid,reading,provenance,stamp)
        changed = db.execute('''UPDATE ibm_inventory_items SET state='consumed',consumed_at=?,
            held_at=coalesce(held_at,?) WHERE item_id=? AND state='held' AND consultation_id=?''',
            (stamp,stamp,item['item_id'],cid))
        if changed.rowcount!=1:
            raise TransactionError('Could not atomically consume the approved IBM sample')
        from .gqtp import record_completion
        record_completion(db,cid)
        db.commit()
        return {'status':'completed','replayed':False, 'consultation_id':cid,
                'item_id':item['item_id'], 'backend':item['backend']}
    except Exception:
        db.rollback()
        raise


def recover_pending(db, *, limit=10):
    """Local-only recovery after interrupted admission; never calls IBM hardware."""
    rows = db.execute('''SELECT r.request_id FROM service_requests r
      WHERE r.service_id='iching.quantum_past' AND r.status='pending'
      ORDER BY r.started_at,r.request_id LIMIT ?''',(limit,)).fetchall()
    return [deliver_pending(db,row['request_id']) for row in rows]
