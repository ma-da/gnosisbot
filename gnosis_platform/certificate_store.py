"""Explicitly invoked certificate issuance; no settlement, provider or mail operations."""
import json,hashlib,os,sqlite3,uuid
from pathlib import Path
from datetime import datetime,timezone
from . import gqtp as g
from .certificate_validation import POLICY, audit_candidate, load_catalog, need, sha
from .certificate_render import VERSION as RENDER_VERSION,render
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA='gnosis.certificate.v2'
LEGACY_SCHEMA='gnosis.certificate.v1'
ROOT=Path(__file__).resolve().parents[1]
COPY_DIGEST='e3579fa6e42661f424118a0a65b37307c4ba5d29a80f7071c7940e9b2235eed0'
ROW_SQL="""SELECT c.consultation_id,c.finished_at,s.service_id,s.request_id,r.schema_version,r.reading_json,r.provenance_json FROM consultations c JOIN service_requests s USING(consultation_id) JOIN reading_results r USING(consultation_id) WHERE c.status='completed' AND s.status='completed'"""

def stamp():return datetime.now(timezone.utc).isoformat()
def canonical(p):return json.dumps(p,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
def key_paths(data):
    folder=Path(data)/'certificates-private'
    return folder/'signing-key-v1.bin',folder/'public-key-v1.txt'
def init_key(db,data):
    priv,pub=key_paths(data)
    if priv.exists() or pub.exists():
        need(priv.is_file() and pub.is_file() and g.public_key(g.read_key(priv))==pub.read_text().strip(),'certificate_key_mismatch');return 'existing'
    need(not db.execute('SELECT 1 FROM reading_certificates LIMIT 1').fetchone(),'certificate_key_missing')
    priv.parent.mkdir(mode=0o700,exist_ok=True)
    need(not priv.parent.is_symlink() and priv.parent.stat().st_mode&0o077==0,'unsafe_key_directory')
    # Explicit initialization only. Never replace a missing key automatically.
    pk=g.new_key(priv)
    fd=os.open(pub,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(pk+'\n');f.flush();os.fsync(f.fileno())
    return 'created'

def copy_registry(root):
    raw=(root/'app/data/certificate_copy_v1.json').read_bytes()
    need(sha(raw)==COPY_DIGEST,'approved_copy_digest_mismatch')
    return json.loads(raw)

def build_payload(db,row,data,root=ROOT):
    h,r=load_catalog(root); copy=copy_registry(root)
    pinned=(Path(data)/'transparency/public/public-key.txt').read_text().strip()
    state,projection=audit_candidate(db,row,g,h,r,pinned)
    if state!='checkpoint_verified':return state,None
    s=row['service_id']; p=json.loads(row['provenance_json']); receipt=g.receipt(db,row['consultation_id'])
    def enrich(x,table,key):
        c=copy[table][str(x[key])];x['title' if table=='hexagrams' else 'name']=c['title'] if table=='hexagrams' else x['name'];x['one_liner']=c['one_liner']
    if projection['format']=='iching.v1':
        for x in ('now','becoming'):enrich(projection[x],'hexagrams','number')
    else:
        for x in projection.get('draws',projection.get('recognized',[])):enrich(x,'runes','rune_id')
    hardware=s.endswith(('.quantum_past','.quantum_future'))
    method={'iching':'I Ching','runes.pouch':'Elder Futhark · Rune Pouch','runes.sticks':'Elder Futhark · Circular Sticks'}[s.rsplit('.',1)[0]]+' · '+{'quantum_past':'Quantum Past','quantum_future':'Quantum Future','qrng_private':'Private QRNG','classic':'Classic'}[s.rsplit('.',1)[1]]
    source={'provider':p['provider'],'label':{'ibm':'IBM Quantum · Live QPU execution','ibm_inventory':'IBM Quantum · Previously recorded QPU casting','qci':'QCI · External quantum randomness','server_crypto':'Server cryptographic randomness'}[p['provider']]}
    if hardware:
        for k in ('backend','circuit_version','circuit_sha256','submitted_at','acquired_at','staged_at','source_quality','batch_id','item_id','sample_selection'):
            if p.get(k) is not None:source[k]=p[k]
        source['ibm_job_id']=p['external_job_id']
        if s.endswith('.quantum_past'):
            source['sample_index_zero_based']=p['sample_index']; inv=receipt['inventory_receipt']; release=inv['checkpoint']['checkpoint']['tree_size']; b=db.execute('SELECT * FROM gqtp_batches WHERE job_id=?',(source['ibm_job_id'],)).fetchone()
            note=json.loads(b['verification_note'] or '{}'); proof=Path(data)/'transparency/public'/f'checkpoint-{release}.json.ots'
            need(b['release_checkpoint']==release and proof.is_file() and sha(proof.read_bytes())==note.get('proof_sha256'),'release_proof_mismatch')
            source['release_checkpoint']=release
            if s.startswith('runes.'):
                from .rune_past_inventory import PROFILES
                mode=s.split('.')[1];need((p['circuit_sha256'],p['circuit_version'])==PROFILES[mode],'rune_circuit_profile_mismatch')
                source.update(logical_qubits=15 if mode=='pouch' else 64,shots_per_casting=1 if mode=='pouch' else 18)
        else:
            if s.startswith('iching.'):
                source['measured_shots']=p['n_shots'];source['selection_method']='128-shot medoid';source['selected_shot_index']=p['selected_shot_index']
            else:
                from .rune_past_inventory import PROFILES
                mode=s.split('.')[1];need((p['circuit_sha256'],p['circuit_version'])==PROFILES[mode],'rune_circuit_profile_mismatch')
                source.update(logical_qubits=15 if mode=='pouch' else 64,shots_per_casting=p['n_shots'])
            # Operator-approved exact digest; never infer qubits merely from the version text.
        profile=db.execute('SELECT * FROM certificate_circuit_profiles WHERE circuit_sha256=? AND circuit_version=?',(p['circuit_sha256'],p['circuit_version'])).fetchone()
        if profile:
            need(not source.get('logical_qubits') or source['logical_qubits']==profile['logical_qubits'],'qubit_profile_conflict')
            source['logical_qubits']=profile['logical_qubits']
            source['logical_qubit_evidence']=profile['evidence']
    payload={'schema':SCHEMA,'certificate_id':uuid.uuid4().hex,'kind':'quantum_hardware' if hardware else 'reading_record','service_id':s,'method_label':method,'reading_completed_at':row['finished_at'],'issued_at':stamp(),'reading':projection,'source':source,'integrity':{'reading_sha256':sha(row['reading_json'].encode()),'provenance_sha256':sha(row['provenance_json'].encode()),'gqtp_event_seq':receipt['event']['seq'],'checkpoint_size':receipt['checkpoint']['checkpoint']['tree_size']},'editorial':{'copy_version':copy['version'],'copy_sha256':COPY_DIGEST},'render_version':RENDER_VERSION}
    return state,payload

def message(payload_hash,asset_hash):return b'GNOSIS-CERTIFICATE-V1\x00'+bytes.fromhex(payload_hash)+bytes.fromhex(asset_hash)
def verify_record(row,data):
    try:
        _,pub=key_paths(data);pk=pub.read_text().strip();p=json.loads(row['payload_json'])
        if not (sha(bytes.fromhex(pk))==row['key_id'] and sha(row['payload_json'].encode('ascii'))==row['payload_sha256'] and canonical(p).decode('ascii')==row['payload_json'] and sha(row['asset_png'])==row['asset_sha256'] and p['certificate_id']==row['certificate_id'] and p['service_id']==row['service_id'] and p['kind']==row['kind'] and p['schema']==row['schema_version'] and p['issued_at']==row['issued_at'] and p['integrity']['checkpoint_size']==row['checkpoint_size'] and p['integrity']['gqtp_event_seq']==row['gqtp_seq'] and p['integrity']['reading_sha256']==row['reading_sha256'] and p['integrity']['provenance_sha256']==row['provenance_sha256']):return False
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pk)).verify(bytes.fromhex(row['signature_hex']),message(row['payload_sha256'],row['asset_sha256']));return True
    except Exception:return False

def issue(db,row,data,root=ROOT,apply=False):
    s=row['service_id'];cid=row['consultation_id']
    if s not in POLICY:return {'service':s,'state':'excluded'}
    old=db.execute('SELECT * FROM reading_certificates WHERE consultation_id=? AND schema_version=?',(cid,SCHEMA)).fetchone()
    if old:
        need(verify_record(old,data),'existing_certificate_invalid')
        need(old['reading_sha256']==sha(row['reading_json'].encode()) and old['provenance_sha256']==sha(row['provenance_json'].encode()),'issued_source_changed')
        return {'service':s,'state':'already_issued','certificate_id':old['certificate_id']}
    state,p=build_payload(db,row,data,root)
    if p is None:return {'service':s,'state':state}
    legacy=db.execute('SELECT * FROM reading_certificates WHERE consultation_id=? AND schema_version=?',(cid,LEGACY_SCHEMA)).fetchone()
    if legacy:
        need(verify_record(legacy,data),'existing_certificate_invalid')
        need(legacy['reading_sha256']==p['integrity']['reading_sha256'] and legacy['provenance_sha256']==p['integrity']['provenance_sha256'],'issued_source_changed')
        # Revise only when the new evidence adds a verified logical count.
        if not p['source'].get('logical_qubits') or json.loads(legacy['payload_json'])['source'].get('logical_qubits')==p['source']['logical_qubits']:
            return {'service':s,'state':'already_issued','certificate_id':legacy['certificate_id']}
    if p['kind']=='quantum_hardware' and not p['source'].get('logical_qubits'):
        p['schema']=LEGACY_SCHEMA
    raw=canonical(p);ph=sha(raw);png=render(p,ph);ah=sha(png)
    if not apply:return {'service':s,'state':'preview_ready','png_bytes':len(png)}
    priv,pub=key_paths(data);key=g.read_key(priv);pk=g.public_key(key);need(pk==pub.read_text().strip(),'certificate_key_mismatch')
    sig=key.sign(message(ph,ah)).hex();kid=sha(bytes.fromhex(pk))
    db.execute('BEGIN IMMEDIATE')
    try:
        fresh=db.execute(ROW_SQL+' AND c.consultation_id=?',(cid,)).fetchone();need(fresh is not None and fresh['reading_json']==row['reading_json'] and fresh['provenance_json']==row['provenance_json'] and fresh['service_id']==s,'source_changed_during_issue')
        existing=db.execute('SELECT * FROM reading_certificates WHERE consultation_id=? AND schema_version=?',(cid,p['schema'])).fetchone()
        if existing:
            need(verify_record(existing,data),'existing_certificate_invalid');db.commit();return {'service':s,'state':'already_issued','certificate_id':existing['certificate_id']}
        db.execute('''INSERT INTO reading_certificates(certificate_id,consultation_id,schema_version,kind,service_id,payload_json,payload_sha256,reading_sha256,provenance_sha256,gqtp_seq,checkpoint_size,copy_version,render_version,asset_png,asset_sha256,signature_hex,key_id,issued_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(p['certificate_id'],cid,p['schema'],p['kind'],s,raw.decode('ascii'),ph,p['integrity']['reading_sha256'],p['integrity']['provenance_sha256'],p['integrity']['gqtp_event_seq'],p['integrity']['checkpoint_size'],p['editorial']['copy_version'],RENDER_VERSION,png,ah,sig,kid,p['issued_at']))
        db.commit()
    except Exception:db.rollback();raise
    return {'service':s,'state':'issued','certificate_id':p['certificate_id'],'png_bytes':len(png)}

def summary(db,item):
    if item.get('status','completed')!='completed' or item.get('service_id') not in POLICY:return
    row=db.execute('SELECT certificate_id FROM reading_certificates WHERE consultation_id=? AND schema_version IN (?,?) ORDER BY schema_version DESC LIMIT 1',(item['consultation_id'],SCHEMA,LEGACY_SCHEMA)).fetchone()
    item['certificate_status']='ready' if row else 'not_issued'
    if row:item['certificate_id']=row['certificate_id']
