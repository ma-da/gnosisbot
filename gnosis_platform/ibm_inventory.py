"""M4A verified IBM Past archive inventory.

A source archive is admitted to QUARANTINE and requires operator approval.
Approval establishes reviewed provenance, NOT cryptographic proof of physical
QPU origin. Import only trusted IBM job exports crosschecked to the IBM portal.
No public routes or credit charges are introduced in M4A.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def valid_sha(s):
    return type(s) is str and len(s)==64 and all(c in '0123456789abcdef' for c in s)


def validate_archive(archive):
    """Validate the explicit M4A archive interchange schema; reject unknown fields.

    Coin bits are bottom-to-top, in groups of three, each bit mapped to 0/1.
    A real IBM export needs metadata connecting these bits to a physical circuit.
    """
    if not isinstance(archive,dict) or set(archive) != {'schema','manifest','samples'}:
        raise ValueError('Expected schema, manifest, samples')
    if archive['schema']!='gnosis.ibm_past.v1':
        raise ValueError('Unsupported archive schema')
    manifest=archive['manifest']
    required={'backend','external_job_id','circuit_sha256','circuit_version','acquired_at','submitted_at'}
    if not isinstance(manifest,dict) or set(manifest)!=required:
        raise ValueError('Manifest keys do not match IBM archive contract')
    if not isinstance(manifest['backend'],str) or not manifest['backend'].startswith('ibm_') or len(manifest['backend'])>80:
        raise ValueError('IBM backend required')
    if not isinstance(manifest['external_job_id'],str) or not 4<=len(manifest['external_job_id'])<=160:
        raise ValueError('IBM external job ID required')
    if not valid_sha(manifest['circuit_sha256']):
        raise ValueError('Circuit SHA256 required')
    if not isinstance(manifest['circuit_version'],str) or not 1<=len(manifest['circuit_version'])<=100:
        raise ValueError('Circuit version required')
    for field in ('acquired_at','submitted_at'):
        try:
            value=datetime.fromisoformat(manifest[field].replace('Z','+00:00'))
            if value.tzinfo is None: raise ValueError()
        except (ValueError,AttributeError,TypeError):
            raise ValueError('UTC/timezone-qualified '+field+' required') from None
    samples=archive['samples']
    if not isinstance(samples,list) or not 1<=len(samples)<=100000:
        raise ValueError('Samples must be nonempty and <=100000 entries')
    seen=set()
    for row in samples:
        if not isinstance(row,dict) or set(row) not in ({'sample_index','coin_bits'}, {'sample_index','coin_bits','moving_qpu_bits'}):
            raise ValueError('Sample must have only sample_index and coin_bits')
        index=row['sample_index'];bits=row['coin_bits']
        if type(index) is not int or not 0<=index<100000000 or index in seen:
            raise ValueError('Invalid or duplicate sample index')
        seen.add(index)
        measured=row.get('moving_qpu_bits')
        if 'moving_qpu_bits' in row and (not isinstance(measured,str) or len(measured)!=6 or set(measured)-{'0','1'}):
            raise ValueError('Measured moving flags must be six bottom-to-top bits')
        if not isinstance(bits,str) or len(bits)!=18 or set(bits)-{'0','1'}:
            raise ValueError('Each sample must contain 18 ordered coin bits')
    return archive


def import_archive(db, archive, *, file_sha256):
    validate_archive(archive)
    if not valid_sha(file_sha256): raise ValueError('Invalid source file checksum')
    manifest=archive['manifest']
    db.execute('BEGIN IMMEDIATE')
    try:
        exists=db.execute('SELECT batch_id FROM ibm_inventory_batches WHERE source_file_sha256=?',
                          (file_sha256,)).fetchone()
        if exists:
            db.commit();return {'batch_id':exists['batch_id'],'created':False}
        batch_id=uuid4().hex
        db.execute('''INSERT INTO ibm_inventory_batches(batch_id,provider,backend,external_job_id,
           circuit_sha256,circuit_version,acquired_at,submitted_at,source_file_sha256,
           imported_at,item_count,status) VALUES(?,'ibm',?,?,?,?,?,?,?,?,?,'quarantined')''',
           (batch_id,manifest['backend'],manifest['external_job_id'],manifest['circuit_sha256'],
            manifest['circuit_version'],manifest['acquired_at'],manifest['submitted_at'],
            file_sha256,utcnow(),len(archive['samples'])))
        for sample in archive['samples']:
            row_hash=hashlib.sha256(canonical(sample).encode()).hexdigest()
            db.execute('''INSERT INTO ibm_inventory_items(
               item_id,batch_id,sample_index,coin_bits,source_record_sha256,moving_qpu_bits)
               VALUES(?,?,?,?,?,?)''',
               (uuid4().hex,batch_id,sample['sample_index'],sample['coin_bits'],row_hash,
                sample.get('moving_qpu_bits')))
        db.commit()
        return {'batch_id':batch_id,'created':True,'imported':len(archive['samples']),'status':'quarantined'}
    except Exception:
        db.rollback();raise


def approve_batch(db,batch_id,*,operator,verified_job_id,verified_circuit_sha256):
    """Require explicit human reconciliation with IBM job and circuit identifiers."""
    if not isinstance(operator,str) or not operator.strip():raise ValueError('Operator required')
    db.execute('BEGIN IMMEDIATE')
    try:
        batch=db.execute('SELECT * FROM ibm_inventory_batches WHERE batch_id=?',(batch_id,)).fetchone()
        if not batch or batch['status']!='quarantined':
            raise ValueError('Unknown or nonquarantined batch')
        if verified_job_id!=batch['external_job_id'] or verified_circuit_sha256!=batch['circuit_sha256']:
            raise ValueError('IBM source verification mismatch')
        db.execute('''UPDATE ibm_inventory_batches
          SET status='approved',approved_by=?,approved_at=? WHERE batch_id=?''',
          (operator,utcnow(),batch_id))
        db.commit()
    except Exception:
        db.rollback();raise


def inventory_counts(db):
    rows=db.execute('''SELECT b.status AS batch_status,i.state,COUNT(*) AS count
        FROM ibm_inventory_items i JOIN ibm_inventory_batches b ON b.batch_id=i.batch_id
        GROUP BY b.status,i.state''').fetchall()
    return [dict(r) for r in rows]


def coin_reading(bits):
    if not isinstance(bits,str) or len(bits)!=18 or set(bits)-{'0','1'}:
        raise ValueError('Invalid coin bits')
    coins=[bits[i:i+3] for i in range(0,18,3)]
    lines=[6+coin.count('1') for coin in coins]
    return {'lines':lines,'coin_bits_bottom_to_top':coins,
            'now_yang_bits_bottom_to_top':[v%2 for v in lines],
            'becoming_yang_bits_bottom_to_top':[(v%2)^int(v in (6,9)) for v in lines],
            'moving_positions_bottom_to_top':[i+1 for i,v in enumerate(lines) if v in (6,9)],
            'casting_method':'three_coins'}


def hold_next(db, consultation_id):
    """Atomically hold one approved unused sample. No charging/settlement here.

    Do not expose this as a public endpoint before the atomic claim+settle
    orchestration/recovery code is installed (M4B).
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        owner=db.execute('''SELECT r.service_id,r.status,r.credits_cost FROM service_requests r
          WHERE r.consultation_id=?''',(consultation_id,)).fetchone()
        if not owner or owner['service_id']!='iching.quantum_past' or owner['status']!='pending' or owner['credits_cost']!=5:
            raise ValueError('Requires a pending five-credit IBM Past consultation')
        existing=db.execute('SELECT * FROM ibm_inventory_items WHERE consultation_id=?',
                            (consultation_id,)).fetchone()
        if existing:
            db.commit();return dict(existing)
        row=db.execute('''SELECT i.item_id FROM ibm_inventory_items i
          JOIN ibm_inventory_batches b ON b.batch_id=i.batch_id
          WHERE b.status='approved' AND i.state='available'
          ORDER BY b.acquired_at,i.batch_id,i.sample_index LIMIT 1''').fetchone()
        if not row:
            db.commit();return None
        stamp=utcnow()
        db.execute('''UPDATE ibm_inventory_items SET state='held',consultation_id=?,held_at=?
          WHERE item_id=? AND state='available' ''',(consultation_id,stamp,row['item_id']))
        out=dict(db.execute('SELECT * FROM ibm_inventory_items WHERE item_id=?',(row['item_id'],)).fetchone())
        db.commit();return out
    except Exception:
        db.rollback();raise


def main():
    import argparse
    from .db import connect,migrate
    p=argparse.ArgumentParser(description='IBM Past verified-inventory management (no live service)')
    sub=p.add_subparsers(dest='cmd',required=True)
    importer=sub.add_parser('import')
    importer.add_argument('archive',type=Path)
    sub.add_parser('status')
    appr=sub.add_parser('approve')
    appr.add_argument('batch_id');appr.add_argument('--operator',required=True)
    appr.add_argument('--verified-job-id',required=True)
    appr.add_argument('--verified-circuit-sha256',required=True)
    args=p.parse_args()
    with connect() as db:
        migrate(db)
        if args.cmd=='import':
            # A very large file may be processed in memory for now; max 100k samples.
            raw=args.archive.read_bytes()
            archive=json.loads(raw)
            outcome=import_archive(db,archive,file_sha256=hashlib.sha256(raw).hexdigest())
            print(json.dumps(outcome,indent=2))
        elif args.cmd=='approve':
            approve_batch(db,args.batch_id,operator=args.operator,
                verified_job_id=args.verified_job_id,
                verified_circuit_sha256=args.verified_circuit_sha256)
            print('Approved after explicit operator verification:',args.batch_id)
        else:
            print(json.dumps(inventory_counts(db),indent=2))


if __name__=='__main__':main()
