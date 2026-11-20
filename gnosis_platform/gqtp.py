"""GQTP v1. No provider/network I/O in transactions. Public fields are allowlisted."""
import hashlib, json, secrets, re
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

VERSION='gqtp.v1'
def stamp(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def canonical(obj):
    # Protocol objects use ASCII keys and string/integer values only. Exact JSON
    # strings (including float-bearing reading payloads) are bound as opaque bytes.
    return json.dumps(obj,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
def sha(raw): return hashlib.sha256(raw).digest()
def hx(raw): return sha(raw).hex()
def require(ok,message):
    if not ok: raise ValueError(message)
def digest_value(value): return hx(canonical(value))
def commitment(opening,nonce):
    n=bytes.fromhex(nonce); require(len(n)==32,'Invalid nonce')
    return hx(b'GQTP1\x00opening\x00'+n+canonical(opening))
def split(n): return 1 << ((n-1).bit_length()-1)
def leaf(data): return sha(b'\x00'+data)
def node(a,b): return sha(b'\x01'+a+b)
def root(leaves):
    if not leaves:return sha(b'')
    if len(leaves)==1:return leaves[0]
    k=split(len(leaves));return node(root(leaves[:k]),root(leaves[k:]))
def proof(leaves,i):
    require(0<=i<len(leaves),'Invalid leaf index')
    if len(leaves)==1:return []
    k=split(len(leaves))
    if i<k:return proof(leaves[:k],i)+[root(leaves[k:]).hex()]
    return proof(leaves[k:],i-k)+[root(leaves[:k]).hex()]
def verify_proof(event,i,n,path,expected):
    try:
        require(type(i) is int and type(n) is int and 0<=i<n,'Invalid index')
        iterator=iter(path)
        def walk(a,b):
            if b==1:return leaf(canonical(event))
            k=split(b)
            left=a<k
            child=walk(a if left else a-k,k if left else b-k)
            sibling=bytes.fromhex(next(iterator));require(len(sibling)==32,'Invalid sibling')
            return node(child,sibling) if left else node(sibling,child)
        return walk(i,n).hex()==expected and next(iterator,None) is None
    except (ValueError,TypeError,StopIteration,RecursionError):return False

def append(db,kind,fields):
    require(db.in_transaction,'Ledger append requires caller transaction')
    seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM gqtp_events').fetchone()[0]
    obj={'schema':VERSION,'seq':seq,'kind':kind,'recorded_at':stamp(),**fields}
    db.execute('INSERT INTO gqtp_events VALUES(?,?)',(seq,canonical(obj).decode('ascii')))
    return seq

def events(db,n=None):
    rows=db.execute('SELECT seq,event_json FROM gqtp_events WHERE seq<=? ORDER BY seq',(n if n is not None else 2**63-1,)).fetchall()
    out=[json.loads(r['event_json']) for r in rows]
    require(all(e['seq']==i and r['seq']==i and canonical(e).decode('ascii')==r['event_json'] for i,(e,r) in enumerate(zip(out,rows),1)),'Ledger gap or noncanonical event')
    if n is not None:require(len(out)==n,'Missing ledger prefix')
    return out

def enforced(db):return db.execute("SELECT value FROM gqtp_settings WHERE key='inventory_enforced'").fetchone()[0]=='1'
def safe_job(value):return value if isinstance(value,str) and re.fullmatch(r'[a-zA-Z0-9_-]{4,160}',value) else None

def record_completion(db,cid,*,legacy=False):
    """Call after complete reading/private archive inserted, before commit."""
    require(db.in_transaction,'Atomic settlement required')
    if db.execute('SELECT 1 FROM gqtp_receipts WHERE consultation_id=?',(cid,)).fetchone():return
    r=db.execute('''SELECT sr.service_id,r.reading_json,r.provenance_json,r.schema_version,r.created_at
        FROM reading_results r JOIN service_requests sr USING(consultation_id) WHERE r.consultation_id=?''',(cid,)).fetchone()
    require(r is not None,'Missing saved result')
    p=json.loads(r['provenance_json']);service=r['service_id']; job=safe_job(p.get('external_job_id')) if service.endswith(('.quantum_past','.quantum_future')) else None
    audit=None
    if service.startswith('runes.'):
        a=db.execute('SELECT archive_sha256,archive_gzip FROM rune_private_archives WHERE consultation_id=?',(cid,)).fetchone()
        require(a is not None,'Missing private rune audit');audit=a[0]
        import gzip
        require(hx(gzip.decompress(a[1]))==audit,'Private rune archive changed')
    opening={'schema':VERSION,'service_id':service,'reading_schema':r['schema_version'],'reading_sha256':hx(r['reading_json'].encode('utf8')),'provenance_sha256':hx(r['provenance_json'].encode('utf8')),'private_archive_sha256':audit}
    public={'service_id':service,'commitment':None,'historical_backfill':int(legacy)}
    if job:public['ibm_job_id']=job
    if service.endswith('.quantum_future') and job:
        require(not db.execute('SELECT 1 FROM gqtp_batches WHERE job_id=?',(job,)).fetchone(),'IBM job already committed to inventory')
        db.execute('INSERT INTO gqtp_live_jobs VALUES(?,?)',(job,cid))
    if service.endswith('.quantum_past'):
        item=db.execute('SELECT * FROM gqtp_items WHERE item_id=?',(p.get('item_id'),)).fetchone()
        if item:
            require(item['disposition']=='commercial' and item['job_id']==job,'Ineligible inventory identity')
            o=json.loads(item['opening_json']);bt,it=batch_tables(o['engine'])
            live=db.execute(f'SELECT * FROM {it} WHERE item_id=?',(p['item_id'],)).fetchone()
            require(live and live['state']=='consumed' and live['consultation_id']==cid and o['sample_index']==live['sample_index'] and p.get('circuit_sha256')==o['circuit_sha256'],'Inventory identity mismatch')
            raw={'coin_bits':live['coin_bits'],'moving_qpu_bits':live['moving_qpu_bits']} if o['engine']=='iching' else json.loads(live['raw_json'])
            require(raw==o['raw'],'Committed measurement changed')
            reading=json.loads(r['reading_json']);actual=reading if o['engine']=='iching' else reading['payload']
            require(digest_value(actual)==o['expected_payload_sha256'],'Delivered reading differs from committed decoding')
            batch=db.execute('SELECT release_checkpoint FROM gqtp_batches WHERE job_id=?',(job,)).fetchone()
            require(batch[0] is not None,'Inventory not released')
            db.execute('INSERT INTO gqtp_deliveries VALUES(?,?)',(item['measurement_id'],cid))
            opening['measurement_id']=item['measurement_id'];public['measurement_id']=item['measurement_id']
        elif enforced(db) and not legacy:raise ValueError('Uncommitted IBM Past sample')
    nonce=secrets.token_hex(32); public['commitment']=commitment(opening,nonce)
    seq=append(db,'reading_delivered' if 'measurement_id' in public else 'reading_completed',public)
    db.execute('INSERT INTO gqtp_receipts VALUES(?,?,?,?)',(cid,seq,canonical(opening).decode('ascii'),nonce))

def backfill(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        rows=db.execute('''SELECT c.consultation_id FROM consultations c JOIN reading_results r USING(consultation_id)
        WHERE c.status='completed' AND NOT EXISTS(SELECT 1 FROM gqtp_receipts q WHERE q.consultation_id=c.consultation_id) ORDER BY r.created_at,c.consultation_id''').fetchall()
        for r in rows:record_completion(db,r[0],legacy=True)
        db.commit();return len(rows)
    except Exception:db.rollback();raise

def public_key(key):return key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex()
def new_key(path):
    import os
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    key=Ed25519PrivateKey.generate()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()));f.flush();os.fsync(f.fileno())
    return public_key(key)
def read_key(path):
    path=Path(path);require(path.is_file() and not path.is_symlink() and path.stat().st_mode&0o077==0,'Signing key must be private regular file (0600)')
    return Ed25519PrivateKey.from_private_bytes(path.read_bytes())
def verify_checkpoint(envelope,pinned):
    try:
        c=envelope['checkpoint']; require(c['schema']==VERSION and c['public_key']==pinned,'Wrong signing key or schema')
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pinned)).verify(bytes.fromhex(envelope['signature']),b'GQTP1\x00checkpoint\x00'+canonical(c))
        return True
    except Exception:return False

def checkpoint(db,key):
    db.execute('BEGIN IMMEDIATE')
    try:
        ev=events(db);n=len(ev);pk=public_key(key)
        prior=db.execute('SELECT envelope_json FROM gqtp_checkpoints ORDER BY tree_size DESC LIMIT 1').fetchone()
        previous=json.loads(prior[0]) if prior else None
        if previous:
            require(verify_checkpoint(previous,pk),'Signing key mismatch or damaged checkpoint')
            old=previous['checkpoint'];require(old['tree_size']<=n and root([leaf(canonical(e)) for e in ev[:old['tree_size']]]).hex()==old['root'],'Earlier checkpoint prefix changed')
            if old['tree_size']==n:db.commit();return previous
        c={'schema':VERSION,'tree_size':n,'root':root([leaf(canonical(e)) for e in ev]).hex(),'public_key':pk,'created_at':stamp(),'previous_checkpoint_sha256':digest_value(previous) if previous else ''}
        envelope={'checkpoint':c,'signature':key.sign(b'GQTP1\x00checkpoint\x00'+canonical(c)).hex()}
        db.execute('INSERT INTO gqtp_checkpoints VALUES(?,?)',(n,canonical(envelope).decode('ascii')));db.commit();return envelope
    except Exception:db.rollback();raise

def receipt(db,cid,n=None):
    row=db.execute('SELECT * FROM gqtp_receipts WHERE consultation_id=?',(cid,)).fetchone();require(row is not None,'No receipt')
    if n is None:
        ch=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size>=? ORDER BY tree_size DESC LIMIT 1',(row['seq'],)).fetchone()
    else:ch=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=? AND tree_size>=?',(n,row['seq'])).fetchone()
    result={'schema':VERSION,'opening':json.loads(row['opening_json']),'nonce':row['nonce_hex'],'event':events(db,row['seq'])[-1],'checkpoint':None,'inclusion_path':None}
    if ch:
        env=json.loads(ch[0]); ev=events(db,env['checkpoint']['tree_size']);result.update(checkpoint=env,inclusion_path=proof([leaf(canonical(e)) for e in ev],row['seq']-1))
    saved=db.execute('SELECT reading_json,provenance_json FROM reading_results WHERE consultation_id=?',(cid,)).fetchone()
    result['saved_bytes']=dict(saved)
    mid=result['opening'].get('measurement_id')
    if mid:
        ir=db.execute('SELECT * FROM gqtp_items WHERE measurement_id=?',(mid,)).fetchone()
        b=db.execute('SELECT release_checkpoint FROM gqtp_batches WHERE job_id=?',(ir['job_id'],)).fetchone()
        env=json.loads(db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(b[0],)).fetchone()[0]); ev=events(db,b[0])
        result['inventory_receipt']={'opening':json.loads(ir['opening_json']),'nonce':ir['nonce_hex'],'event':ev[ir['seq']-1],'checkpoint':env,'inclusion_path':proof([leaf(canonical(e)) for e in ev],ir['seq']-1)}
    return result

def verify_receipt(r,pinned):
    try:
        e=r['event'];env=r['checkpoint'];c=env['checkpoint']
        o=r['opening'];data=r['saved_bytes']
        okay=(verify_checkpoint(env,pinned) and commitment(o,r['nonce'])==e['commitment'] and o['service_id']==e['service_id'] and verify_proof(e,e['seq']-1,c['tree_size'],r['inclusion_path'],c['root']) and o['reading_sha256']==hx(data['reading_json'].encode('utf8')) and o['provenance_sha256']==hx(data['provenance_json'].encode('utf8')))
        if 'measurement_id' in o:
            inv=r['inventory_receipt'];okay=okay and o['measurement_id']==e['measurement_id']==inv['opening']['measurement_id'] and verify_inventory_receipt(inv,pinned) and inv['event']['disposition']=='commercial' and inv['event']['seq']<e['seq']
            reading=json.loads(data['reading_json']);actual=reading if inv['opening']['engine']=='iching' else reading['payload']
            okay=okay and digest_value(actual)==inv['opening']['expected_payload_sha256']
        return bool(okay)
    except Exception:return False

def verify_inventory_receipt(r,pinned):
    try:
        e=r['event'];env=r['checkpoint'];c=env['checkpoint'];o=r['opening']
        return (verify_checkpoint(env,pinned) and commitment(o,r['nonce'])==e['commitment'] and o['measurement_id']==e['measurement_id'] and o['job_id']==e['ibm_job_id'] and o['engine']==e['engine'] and measurement_id(o['job_id'],o['sample_index'],o['engine'])==e['measurement_id'] and verify_proof(e,e['seq']-1,c['tree_size'],r['inclusion_path'],c['root']))
    except Exception:return False

def measurement_id(job,index,engine):
    width=18 if engine=='sticks' else 1
    return digest_value({'schema':'gqtp.physical.v1','provider':'ibm','job_id':job,'pub_index':0,'shot_start':index*width,'shot_count':width})

def batch_tables(engine):
    require(engine in ('iching','pouch','sticks'),'Unknown engine')
    prefix='ibm' if engine=='iching' else 'rune'
    return prefix+'_inventory_batches',prefix+'_inventory_items'

def register_batch(db,engine,bid,*,demo_count=0,excluded=(),confirm_unrevealed=False):
    """Commit already imported, qualified quarantine. No approval performed here."""
    require(confirm_unrevealed is True,'Explicit unrevealed stock confirmation required')
    require(type(demo_count) is int and demo_count>=0 and (engine=='iching' or demo_count==0),'Invalid demo count')
    bt,it=batch_tables(engine);db.execute('BEGIN IMMEDIATE')
    try:
        b=db.execute(f'SELECT * FROM {bt} WHERE batch_id=?',(bid,)).fetchone()
        require(b and b['status']=='quarantined','Batch must be quarantined')
        job=b['external_job_id'];require(safe_job(job)==job,'Invalid job ID')
        if engine!='iching':require(b['mode']==engine,'Wrong engine')
        require(not db.execute('SELECT 1 FROM gqtp_batches WHERE job_id=? OR batch_id=?',(job,bid)).fetchone(),'Already committed')
        require(not db.execute('SELECT 1 FROM ibm_future_jobs WHERE external_job_id=?',(job,)).fetchone(),'Job already used for live reading')
        require(not db.execute('SELECT 1 FROM gqtp_live_jobs WHERE job_id=?',(job,)).fetchone(),'Job already used for live reading')
        # One job is one inventory batch (all current qualified profiles use PUB 0).
        for table in ('ibm_inventory_batches','rune_inventory_batches'):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                require(not db.execute(f'SELECT 1 FROM {table} WHERE external_job_id=? AND batch_id<>?',(job,bid)).fetchone(),'Duplicate job inventory')
        q=db.execute('SELECT metadata_json FROM gqtp_qualifications WHERE batch_id=?',(bid,)).fetchone()
        if enforced(db):require(q is not None,'Missing IBM archive qualification')
        if q:
            qm=json.loads(q[0]);require(qm['mode']==engine and qm['external_job_id']==job and qm['circuit_sha256']==b['circuit_sha256'] and qm['archive_sha256']==(b['source_file_sha256'] if engine=='iching' else b['archive_sha256']),'Qualification mismatch')
        rows=db.execute(f'SELECT * FROM {it} WHERE batch_id=? ORDER BY sample_index',(bid,)).fetchall()
        require(len(rows)==b['item_count'] and len(rows)>0,'Incomplete archive')
        excluded=set(excluded);require(excluded <= {r['sample_index'] for r in rows},'Unknown excluded sample')
        require(all(r['state'] in ('available','void') and r['consultation_id'] is None for r in rows),'Previously allocated stock')
        eligible=[r for r in rows if r['state']=='available' and r['sample_index'] not in excluded]
        require(len(eligible)>demo_count,'No commercial stock after exclusions')
        demos={r['sample_index'] for r in eligible[:demo_count]}
        public={'engine':engine,'ibm_job_id':job,'backend':b['backend'],'circuit_sha256':b['circuit_sha256'],'acquired_at':b['acquired_at'],'circuit_version':b['circuit_version'],'archive_sha256':b['source_file_sha256'] if engine=='iching' else b['archive_sha256'],'count':len(rows),'commercial_count':len(eligible)-demo_count,'demo_count':demo_count,'excluded_count':len(rows)-len(eligible)}
        if q:
            # Decimal text avoids floating point serialization ambiguity in public events.
            for k in ('qpu_seconds','resource_units'):
                public[k]=str(qm[k]) if qm[k] is not None else 'unknown'
        seq=append(db,'batch_committed',public)
        db.execute('INSERT INTO gqtp_batches(job_id,engine,batch_id,seq) VALUES(?,?,?,?)',(job,engine,bid,seq))
        for r in rows:
            i=r['sample_index'];disp='excluded' if r['state']=='void' or i in excluded else ('demo' if i in demos else 'commercial')
            mid=measurement_id(job,i,engine)
            raw={'coin_bits':r['coin_bits'],'moving_qpu_bits':r['moving_qpu_bits']} if engine=='iching' else json.loads(r['raw_json'])
            opening={'schema':VERSION,'measurement_id':mid,'job_id':job,'engine':engine,'sample_index':i,'circuit_sha256':b['circuit_sha256'],'circuit_version':b['circuit_version'],'raw':raw}
            if disp!='excluded':opening['expected_payload_sha256']=digest_value(decoded_payload(engine,raw))
            nonce=secrets.token_hex(32)
            event={'engine':engine,'ibm_job_id':job,'measurement_id':mid,'disposition':disp,'commitment':commitment(opening,nonce)}
            iseq=append(db,'inventory_committed',event)
            db.execute('INSERT INTO gqtp_items VALUES(?,?,?,?,?,?,?,?)',(mid,job,r['item_id'],i,iseq,disp,canonical(opening).decode('ascii'),nonce))
            if disp!='commercial':db.execute(f"UPDATE {it} SET state='void' WHERE item_id=?",(r['item_id'],))
        db.commit();return public
    except Exception:db.rollback();raise

def enable_inventory_guard(db):
    """One-way operator activation. Existing approved unsafe stock must be reconciled first."""
    db.execute('BEGIN IMMEDIATE')
    try:
        for bt,it in [batch_tables('iching'),batch_tables('pouch')]:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(bt,)).fetchone():continue
            require(not db.execute(f"SELECT 1 FROM {bt} b WHERE status='approved' AND NOT EXISTS(SELECT 1 FROM gqtp_batches q WHERE q.batch_id=b.batch_id AND release_checkpoint IS NOT NULL)").fetchone(),'Already approved unregistered stock; reconcile first')
            if bt.startswith('rune'):
                db.execute("""CREATE TRIGGER IF NOT EXISTS gqtp_rune_item_state BEFORE UPDATE OF state ON rune_inventory_items WHEN EXISTS(SELECT 1 FROM gqtp_items q WHERE q.item_id=OLD.item_id AND (q.disposition<>'commercial' AND NEW.state<>'void' OR OLD.state IN ('void','consumed') AND NEW.state<>OLD.state)) BEGIN SELECT RAISE(ABORT,'GQTP excluded or consumed sample cannot be recycled'); END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS gqtp_rune_batch_frozen BEFORE UPDATE OF external_job_id,circuit_sha256,circuit_version,backend,acquired_at,submitted_at,archive_sha256,item_count ON rune_inventory_batches WHEN EXISTS(SELECT 1 FROM gqtp_batches WHERE batch_id=OLD.batch_id) BEGIN SELECT RAISE(ABORT,'GQTP batch provenance immutable'); END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS gqtp_rune_approval_guard BEFORE UPDATE OF status ON rune_inventory_batches WHEN NEW.status='approved' AND NOT EXISTS(SELECT 1 FROM gqtp_batches q WHERE q.batch_id=NEW.batch_id AND q.job_id=NEW.external_job_id AND q.release_checkpoint IS NOT NULL) BEGIN SELECT RAISE(ABORT,'GQTP release required'); END""")
                for op,ref in [('INSERT','NEW'),('DELETE','OLD'),('UPDATE OF batch_id,sample_index,raw_json,raw_sha256','OLD')]:
                    name=op.split()[0].lower()
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS gqtp_rune_frozen_{name} BEFORE {op} ON rune_inventory_items WHEN EXISTS(SELECT 1 FROM gqtp_batches WHERE batch_id={ref}.batch_id) BEGIN SELECT RAISE(ABORT,'GQTP measurement immutable'); END")
        db.execute("UPDATE gqtp_settings SET value='1' WHERE key='inventory_enforced'");db.commit()
    except Exception:db.rollback();raise

def release_batch(db,job,n,*,proof_sha256,operator):
    """Local CLI only, after successful external `ots verify`. Does not approve stock."""
    require(operator.strip() and re.fullmatch(r'[0-9a-f]{64}',proof_sha256),'Verification evidence required')
    db.execute('BEGIN IMMEDIATE')
    try:
        b=db.execute('SELECT * FROM gqtp_batches WHERE job_id=?',(job,)).fetchone();require(b and b['release_checkpoint'] is None,'Unknown or released batch')
        ch=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(n,)).fetchone();require(ch,'Unknown checkpoint')
        require(n>=db.execute('SELECT MAX(seq) FROM gqtp_items WHERE job_id=?',(job,)).fetchone()[0],'Checkpoint omits stock')
        note={'method':'operator_ots_verify','proof_sha256':proof_sha256,'operator':operator,'verified_at':stamp()}
        db.execute('UPDATE gqtp_batches SET release_checkpoint=?,verification_note=? WHERE job_id=?',(n,canonical(note).decode('ascii'),job))
        append(db,'batch_released',{'ibm_job_id':job,'checkpoint_size':n,'ots_proof_sha256':proof_sha256})
        db.commit()
    except Exception:db.rollback();raise


def decoded_payload(engine,raw):
    if engine=='iching':
        from .ibm_inventory import coin_reading
        r=coin_reading(raw['coin_bits']);r['casting_method']='ibm_archived_three_coin_qpu'
        flags=raw['moving_qpu_bits']
        if flags is not None:
            r['moving_qpu_bits_bottom_to_top']=flags
            r['moving_flag_matches']=sum(a==b for a,b in zip(''.join('1' if v in (6,9) else '0' for v in r['lines']),flags))
        return r
    from .rune_oracle_adapter import pouch_payload,sticks_payload
    return (pouch_payload(raw) if engine=='pouch' else sticks_payload(raw))['payload']

def note_qualification(db,bid,meta):
    require(meta.get('remote_measurements_match') is True,'IBM measurement comparison required')
    fields=('mode','backend','external_job_id','circuit_sha256','circuit_version','archive_sha256','acquired_at','submitted_at','qpu_seconds','resource_units','remote_measurements_match')
    value=canonical({k:meta.get(k) for k in fields}).decode('ascii')
    old=db.execute('SELECT metadata_json FROM gqtp_qualifications WHERE batch_id=?',(bid,)).fetchone()
    if old:
        require(old[0]==value,'Existing qualification differs; reconcile before use');return
    db.execute('INSERT INTO gqtp_qualifications VALUES(?,?)',(bid,value))
