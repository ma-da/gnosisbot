"""Verify exact detached proof and atomically release eligible committed stock."""
import hashlib, json, os, re, subprocess, tempfile
from pathlib import Path
from . import gqtp as g
from .admin_metrics import stamp
from .admin_btc_release import release_verified

def check(db,n,public_dir,ots,run=subprocess.run,*,promote_job=None):
    r=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(n,)).fetchone()
    if not r:raise LookupError('Unknown checkpoint')
    f=public_dir/f'checkpoint-{n}.json'; p=f.with_suffix('.json.ots')
    try:
        cp=f.read_bytes(); key=(public_dir/'public-key.txt').read_text().strip()
        if cp!=r[0].encode('ascii') or not g.verify_checkpoint(json.loads(cp),key):raise ValueError('Signed checkpoint mismatch')
        if not p.is_file() or not 0<p.stat().st_size<=2*1024*1024:raise ValueError('Missing or oversized proof')
        proof=p.read_bytes()
    except OSError as e:raise ValueError('Missing checkpoint, proof or public key') from e
    sha=lambda b:hashlib.sha256(b).hexdigest()
    status='verification_unavailable'; heights=[]; evidence={}
    mode=os.getenv('GNOSIS_BTC_VERIFIER','core')
    if mode not in ('core','explorers'):raise ValueError('Unknown BTC verifier')
    method='ots_bitcoin_core' if mode=='core' else 'ots_dual_explorer_headers'
    # Verify a private, consistent snapshot. Never upgrade or change the original proof here.
    try:
        with tempfile.TemporaryDirectory(prefix='gqtp-check-') as tmp:
            tf=Path(tmp)/f.name; tp=tf.with_suffix('.json.ots');tf.write_bytes(cp);tp.write_bytes(proof)
            info=run([ots,'info',str(tp)],capture_output=True,text=True,timeout=10,check=False)
            if info.returncode!=0:status='proof_invalid_or_unreadable'
            else:
                heights=sorted(set(map(int,re.findall(r'BitcoinBlockHeaderAttestation\((\d+)\)',info.stdout))))
                # CLI info must identify these exact checkpoint bytes.
                if not re.search(r'File sha256 hash:\s*'+sha(cp)+r'\b',info.stdout):status='proof_checkpoint_mismatch'
                elif not heights:status='pending_attestation'
                else:
                    if mode=='core':
                        v=run([ots,'--no-default-whitelist','verify',str(tp)],capture_output=True,text=True,timeout=45,check=False)
                        status='bitcoin_verified' if v.returncode==0 else 'attestation_present_not_verified'
                    else:
                        python=str(Path(ots).expanduser().parent/'python')
                        helper=Path(__file__).resolve().parents[1]/'scripts'/'gqtp_verify_explorers.py'
                        v=run([python,str(helper),str(tf),str(tp)],capture_output=True,text=True,timeout=100,check=False)
                        if v.returncode==0:
                            evidence=json.loads(v.stdout)
                            if evidence.get('height') not in heights or evidence.get('confirmations_min',0)<6:raise ValueError('Invalid explorer evidence')
                            status='bitcoin_verified'
                        else:status='attestation_present_not_verified'
    except (OSError,subprocess.TimeoutExpired):status='attestation_present_not_verified' if heights else 'verification_unavailable'
    if f.read_bytes()!=cp or p.read_bytes()!=proof:raise ValueError('Proof changed during check; retry')
    checked=stamp(); released=[]
    db.execute('BEGIN IMMEDIATE')
    try:
        if status=='bitcoin_verified':
            released=release_verified(db,n,cp,sha(proof),method,evidence,promote_job=promote_job) if g.enforced(db) else []
            if promote_job is not None:g.require(len(released)==1,'Reserve promotion failed')
        db.execute('INSERT INTO gnosis_admin_btc_checks VALUES(?,?,?,?,?,?) ON CONFLICT(tree_size) DO UPDATE SET proof_sha256=excluded.proof_sha256,checkpoint_sha256=excluded.checkpoint_sha256,status=excluded.status,checked_at=excluded.checked_at,block_heights_json=excluded.block_heights_json',(n,sha(proof),sha(cp),status,checked,json.dumps(heights)))
        db.execute('INSERT INTO gnosis_admin_snapshots(name,payload_json,observed_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json,observed_at=excluded.observed_at',(f'btc_check_{n}',json.dumps({'method':method,'evidence':evidence,'proof_sha256':sha(proof),'checkpoint_sha256':sha(cp),'status':status},sort_keys=True),checked))
        db.commit()
    except Exception:
        db.rollback();raise
    return dict(tree_size=n,status=status,checked_at=checked,block_heights=heights,proof_sha256=sha(proof),inventory_changed=bool(released),released_batches=released,released_readings=sum(r['commercial_count'] for r in released),verification_method=method,evidence=evidence)
