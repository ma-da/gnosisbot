"""Public aggregate GQTP inventory. No raw data, account IDs or private openings."""
from contextlib import closing
from datetime import datetime, timezone
import os
from fastapi import APIRouter, HTTPException, Response
from .db import connect
from .config import get_settings

router = APIRouter(tags=['public-inventory'])
ENGINES = {'iching': ('I Ching', 'iching.quantum_past'),
           'pouch': ('Rune Pouch', 'runes.pouch.quantum_past'),
           'sticks': ('Circular Sticks', 'runes.sticks.quantum_past')}


def enabled(engine):
    if os.environ.get('GNOSIS_ENABLE_ACCOUNTS_API') != '1':
        return False
    if engine == 'iching':
        return os.environ.get('GNOSIS_ENABLE_IBM_PAST') == '1'
    return os.environ.get('GNOSIS_ENABLE_RUNES') == '1' and os.environ.get('GNOSIS_ENABLE_RUNE_PAST') == '1'


def snapshot(db, public_dir):
    """All counts reflect one SQLite snapshot. Never equate quarantine with stock."""
    # No raw columns are selected. Qualification is a recorded operator check,
    # not an independent public proof of IBM origin.
    import json
    cp = db.execute('SELECT tree_size,envelope_json FROM gqtp_checkpoints ORDER BY tree_size DESC').fetchall()
    sizes = [r['tree_size'] for r in cp]
    # A present detached proof is evidence of a saved submission, NOT validation.
    stamped = []
    for r in cp:
        size = r['tree_size']
        f = public_dir / f'checkpoint-{size}.json'
        p = f.with_suffix('.json.ots')
        try:
            if p.is_file() and p.stat().st_size > 0 and f.read_bytes() == r['envelope_json'].encode('ascii'):
                stamped.append(size)
        except OSError:
            continue
    guard = db.execute("SELECT value FROM gqtp_settings WHERE key='inventory_enforced'").fetchone()
    enforced = bool(guard and guard[0] == '1')
    result=[]
    for engine,(label,service) in ENGINES.items():
        prefix = 'ibm' if engine == 'iching' else 'rune'
        # These SQL identifiers are fixed constants, not user input.
        rows=db.execute(f'''SELECT q.job_id,q.release_checkpoint,q.seq,b.status,
             max(i.seq) AS last_seq, k.metadata_json AS qualification
             FROM gqtp_batches q JOIN {prefix}_inventory_batches b ON b.batch_id=q.batch_id
             JOIN gqtp_items i ON i.job_id=q.job_id
             LEFT JOIN gqtp_qualifications k ON k.batch_id=q.batch_id
             WHERE q.engine=? GROUP BY q.job_id,q.release_checkpoint,q.seq,b.status,k.metadata_json
             ORDER BY q.seq''',(engine,)).fetchall()
        totals=dict(committed=0,commercial=0,available=0,approved_available=0,pending_release=0,
                    reserved=0,delivered=0,demo=0,excluded=0,unavailable=0)
        checks={k:0 for k in ['ibm_matched','committed','signed','timestamp_submitted','bitcoin_verified','released']}
        batches=[]
        for r in rows:
            job=r['job_id']; last=r['last_seq']; released=r['release_checkpoint'] is not None and r['status']=='approved'
            verified=r['release_checkpoint'] is not None
            signed=any(n>=last for n in sizes)
            submitted=any(n>=last for n in stamped) or verified
            try: matched=json.loads(r['qualification'] or '{}').get('remote_measurements_match') is True
            except (ValueError,TypeError,AttributeError): matched=False
            stages=dict(ibm_matched=matched,committed=True,signed=signed,timestamp_submitted=submitted,
                        bitcoin_verified=verified,released=released)
            for k,v in stages.items(): checks[k]+=int(v)
            counts=dict(committed=0,commercial=0,available=0,approved_available=0,pending_release=0,
                        reserved=0,delivered=0,demo=0,excluded=0,unavailable=0)
            groups=db.execute(f'''SELECT q.disposition,i.state,COUNT(*) AS n
                FROM gqtp_items q LEFT JOIN {prefix}_inventory_items i ON i.item_id=q.item_id
                WHERE q.job_id=? GROUP BY q.disposition,i.state''',(job,)).fetchall()
            for gr in groups:
                n=gr['n']; disp=gr['disposition']; state=gr['state']; counts['committed']+=n
                if disp in ('demo','excluded'):
                    counts[disp]+=n; continue
                counts['commercial']+=n
                if state=='consumed': counts['delivered']+=n
                elif state=='held': counts['reserved']+=n
                elif state=='available' and released:
                    counts['approved_available']+=n
                    if enforced and enabled(engine): counts['available']+=n
                elif state=='available' and r['status']=='quarantined': counts['pending_release']+=n
                else: counts['unavailable']+=n
            for k,v in counts.items(): totals[k]+=v
            batches.append({'ibm_job_id':job,'status':r['status'],'counts':counts,'checks':stages,
                            'signed_checkpoint':next((n for n in reversed(sizes) if n>=last),None),
                            'release_checkpoint':r['release_checkpoint']})
        result.append(dict(engine=engine,label=label,service_id=service,service_enabled=enabled(engine),
                           counts=totals,batch_count=len(rows),check_counts=checks,batches=batches))
    return {'schema_version':'gnosis.public-inventory.v1','as_of':datetime.now(timezone.utc).isoformat(),
            'inventory_enforced':enforced,'latest_checkpoint':max(sizes,default=None),'engines':result}


def load_snapshot(connect_db=connect):
    with closing(connect_db()) as db:
        db.execute('BEGIN')
        try: return snapshot(db,get_settings().data_dir/'transparency'/'public')
        finally: db.rollback()


@router.get('/transparency/inventory')
def public_inventory(response: Response):
    response.headers['Cache-Control']='no-store'
    try: return load_snapshot()
    except Exception as e: raise HTTPException(503,'Inventory status unavailable') from e
