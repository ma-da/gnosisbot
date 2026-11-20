"""Finite archived hardware stock. No IBM calls, substitutions or rerolls."""
import hashlib, json, math
from datetime import datetime
from uuid import uuid4
from .identity import iso, now
from .rune_oracle_adapter import pouch_payload, sticks_payload
from .rune_services import SCHEMA, spec
from quantum.pouch.decoder import decode_ranks
from quantum.sticks.decoder import decode_casting

PROFILES={'pouch':('f987202e9fc45236ca92aae6c6f2786a30ee656d6c23a2fc0f11d465f741a27a','strict-v2a-1.0.0'),
          'sticks':('45cd8d510fb3fa481c38a93ce0b3417175b2f753cce2622248f3e278c6da6d8e','circular-sticks-1.1.0')}

def compact(o):return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def sha(s):return hashlib.sha256(s.encode()).hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def available_count(db,mode):
    return db.execute("""SELECT count(*) FROM rune_inventory_items i JOIN rune_inventory_batches b USING(batch_id)
        WHERE b.mode=? AND b.status='approved' AND i.state='available'""",(mode,)).fetchone()[0]

def read_counts(db):
    return [dict(r) for r in db.execute("""SELECT b.mode,b.status AS batch_status,i.state,count(*) AS count
      FROM rune_inventory_items i JOIN rune_inventory_batches b USING(batch_id) GROUP BY b.mode,b.status,i.state""")]

def valid_raw(mode,raw):
    if mode=='pouch':
        require(isinstance(raw,list) and len(raw)==3 and all(type(x) is int and 0<=x<32 for x in raw),'Malformed pouch ranks')
        return decode_ranks(raw) is not None
    if mode=='sticks':
        decode_casting(raw,width=64)
        return True
    raise ValueError('Unknown mode')

def import_batch(db,meta,records,*,excluded=()):
    """Imported only by trusted local CLI after exact IBM result comparison.
    Source bytes/receipt remain in the independent protected filesystem archive.
    Invalid ranks are retained as void. Exclusions must be selected before import.
    """
    mode=meta['mode']; require(mode in PROFILES,'Unknown mode')
    profile,version=PROFILES[mode]
    require(meta['backend']=='ibm_marrakesh' and meta['circuit_sha256']==profile and meta['circuit_version']==version,'Unqualified physical profile')
    require(isinstance(records,list) and len(records)==128,'Expected frozen 128-casting batch')
    require(isinstance(meta['external_job_id'],str) and 4<=len(meta['external_job_id'])<=160,'Missing job ID')
    require(isinstance(meta['archive_sha256'],str) and len(meta['archive_sha256'])==64 and set(meta['archive_sha256'])<=set('0123456789abcdef'),'Missing archive hash')
    times=[datetime.fromisoformat(meta[k].replace('Z','+00:00')) for k in ('submitted_at','acquired_at')]
    require(all(t.tzinfo is not None for t in times) and times[0]<=times[1],'Invalid hardware timestamps')
    excluded=set(excluded);require(all(type(i) is int and 0<=i<len(records) for i in excluded),'Invalid excluded index')
    for key in ('qpu_seconds','resource_units'):
        value=meta.get(key)
        require(value is None or (type(value) in (int,float) and math.isfinite(value) and (value>0 if key=='qpu_seconds' else value>=0)),'Invalid usage metric')
    prepared=[]
    for idx,raw in enumerate(records):
        good=valid_raw(mode,raw); reason='invalid_hardware_rank' if not good else ('previously_revealed_or_reserved' if idx in excluded else None)
        data=compact(raw);prepared.append((idx,data,sha(data),'void' if reason else 'available',reason))
    db.execute('BEGIN IMMEDIATE')
    try:
        old=db.execute('SELECT * FROM rune_inventory_batches WHERE external_job_id=?',(meta['external_job_id'],)).fetchone()
        if old:
            require(old['archive_sha256']==meta['archive_sha256'] and old['mode']==mode,'Job already imported from a different archive')
            db.commit();return {'batch_id':old['batch_id'],'status':old['status'],'created':False}
        for table in ('ibm_inventory_batches','ibm_future_jobs'):
            require(not db.execute(f'SELECT 1 FROM {table} WHERE external_job_id=?',(meta['external_job_id'],)).fetchone(),'Job already assigned to I Ching')
        bid=uuid4().hex
        db.execute('''INSERT INTO rune_inventory_batches(batch_id,mode,external_job_id,backend,circuit_sha256,circuit_version,archive_sha256,acquired_at,submitted_at,imported_at,item_count,qpu_seconds,resource_units)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(bid,mode,meta['external_job_id'],meta['backend'],profile,version,meta['archive_sha256'],meta['acquired_at'],meta['submitted_at'],iso(now()),len(records),meta.get('qpu_seconds'),meta.get('resource_units')))
        db.executemany('INSERT INTO rune_inventory_items(item_id,batch_id,sample_index,raw_json,raw_sha256,state,exclusion_reason) VALUES(?,?,?,?,?,?,?)',[(uuid4().hex,bid,*row) for row in prepared])
        db.commit();return {'batch_id':bid,'status':'quarantined','created':True,'candidate_count':sum(x[3]=='available' for x in prepared),'void_count':sum(x[3]=='void' for x in prepared)}
    except Exception:db.rollback();raise

def approve(db,bid,*,operator,job_id,profile_sha,confirm_unrevealed):
    require(confirm_unrevealed is True and isinstance(operator,str) and operator.strip(),'Explicit operator and unrevealed-stock confirmation required')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT * FROM rune_inventory_batches WHERE batch_id=?',(bid,)).fetchone()
        require(row and row['status']=='quarantined' and row['external_job_id']==job_id and row['circuit_sha256']==profile_sha,'Batch or verification mismatch')
        db.execute("UPDATE rune_inventory_batches SET status='approved',approved_at=?,approved_by=? WHERE batch_id=?",(iso(now()),operator,bid));db.commit()
    except Exception:db.rollback();raise

def stage_past(db,request):
    """Atomic hold + durable staging. No reading data leaves the transaction."""
    from .transactions import _get_request
    rid=request['request_id'];mode,source,_=spec(request['service_id']);require(source=='quantum_past','Not a Past request')
    db.execute('BEGIN IMMEDIATE')
    try:
        fresh=_get_request(db,rid)
        require(fresh and fresh['service_id']==request['service_id'],'Unknown Past request')
        if fresh['status']!='pending':db.commit();return fresh['status']
        old=db.execute('SELECT status FROM rune_executions WHERE request_id=?',(rid,)).fetchone()
        if old:
            require(old['status']=='staged','Unexpected Past execution claim');db.commit();return 'staged'
        item=db.execute("""SELECT i.*,b.mode,b.backend,b.external_job_id,b.circuit_sha256,b.circuit_version,b.archive_sha256,b.acquired_at,b.submitted_at,b.approved_at
           FROM rune_inventory_items i JOIN rune_inventory_batches b USING(batch_id)
           WHERE b.mode=? AND b.status='approved' AND i.state='available'
           ORDER BY b.acquired_at,b.batch_id,i.sample_index LIMIT 1""",(mode,)).fetchone()
        if item is None:db.commit();return 'out_of_stock'
        raw=json.loads(item['raw_json']);require(sha(compact(raw))==item['raw_sha256'] and valid_raw(mode,raw),'Damaged inventory record')
        stamp=iso(now())
        provenance={k:item[k] for k in ('backend','external_job_id','circuit_sha256','circuit_version','archive_sha256','acquired_at','submitted_at','approved_at','batch_id','item_id','sample_index','raw_sha256')}
        provenance.update(provider='ibm_inventory',source_quality='operator_reviewed_hardware_archive',qpu_circuit_executed=True,new_qpu_execution=False,fallback_used=False,sample_selection='first_unused_approved_sample_v1',entropy_bits=15 if mode=='pouch' else 1152)
        db.execute("UPDATE rune_inventory_items SET state='held',consultation_id=?,held_at=? WHERE item_id=? AND state='available'",(fresh['consultation_id'],stamp,item['item_id']))
        db.execute("INSERT INTO rune_executions VALUES(?,'staged',?,?,?)",(rid,stamp,compact({'raw':raw,'provenance':provenance}),stamp))
        db.commit();return 'staged'
    except Exception:db.rollback();raise

def build_past_reading(service_id,cid,staged):
    mode,source,provider=spec(service_id);raw=staged['raw'];p=dict(staged['provenance'])
    require(source=='quantum_past' and p['provider']==provider and p['circuit_sha256']==PROFILES[mode][0] and p['raw_sha256']==sha(compact(raw)) and valid_raw(mode,raw),'Invalid staged hardware sample')
    decoded=pouch_payload(raw) if mode=='pouch' else sticks_payload(raw)
    if mode=='pouch':p['engine_version']='ordered-rank-decoder-v1'
    else:p.update(recognition_version=decoded['recognition_version'],profile_sha256=decoded['profile_sha256'])
    reading={'schema_version':SCHEMA,'reading_id':cid,'mode':mode,'source':'ibm_qpu','delivery':'precomputed','status':'ready','provenance':p,'payload':decoded['payload']}
    return reading,p,{'entropy':staged,'audit':decoded['private_audit']}

def consume(db,row,staged,stamp):
    """Called inside the shared atomic settlement, never independently."""
    p=staged['provenance'];mode,_,_=spec(row['service_id'])
    i=db.execute('''SELECT i.*,b.mode,b.status AS batch_status,b.external_job_id,b.circuit_sha256,b.archive_sha256
      FROM rune_inventory_items i JOIN rune_inventory_batches b USING(batch_id) WHERE i.item_id=?''',(p['item_id'],)).fetchone()
    require(i and i['mode']==mode and i['batch_status']=='approved' and i['state']=='held' and i['consultation_id']==row['consultation_id'] and i['raw_sha256']==p['raw_sha256'] and i['raw_json']==compact(staged['raw']) and all(i[k]==p[k] for k in ('external_job_id','circuit_sha256','archive_sha256','batch_id','sample_index')),'Inventory settlement does not match held original')
    require(db.execute("UPDATE rune_inventory_items SET state='consumed',consumed_at=? WHERE item_id=? AND state='held' AND consultation_id=?",(stamp,p['item_id'],row['consultation_id'])).rowcount==1,'Inventory consumption failed')

def void_failed_hold(db,row):
    # Preserve the original measurement for audit; never recycle a failed hold.
    db.execute("UPDATE rune_inventory_items SET state='void',exclusion_reason='failed_consultation_hold' WHERE consultation_id=? AND state='held'",(row['consultation_id'],))
