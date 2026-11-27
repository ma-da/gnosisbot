"""Certificate-only reconciliation. No provider, email, credit or inventory operations."""
import os,json,tempfile
from pathlib import Path
from . import gqtp as g
from .certificate_store import ROW_SQL,SCHEMA,LEGACY_SCHEMA,issue,stamp,ROOT
from .certificate_validation import POLICY,need,sha,load_catalog,audit_candidate

FUTURE_VERSION='iching_now_becoming_24q_seed5_v1'

def review_profile(db,job,data,root=ROOT):
    row=db.execute(ROW_SQL+''' AND s.service_id='iching.quantum_future' AND s.request_id IN (SELECT request_id FROM ibm_future_jobs WHERE external_job_id=?)''',(job,)).fetchone()
    need(row is not None,'no_completed_future_job')
    h,r=load_catalog(root);pinned=(data/'transparency/public/public-key.txt').read_text().strip()
    state,_=audit_candidate(db,row,g,h,r,pinned);need(state=='checkpoint_verified','profile_requires_verified_reading')
    p=json.loads(row['provenance_json']);need(p['circuit_version']==FUTURE_VERSION,'unrecognized_future_profile')
    from quantum.iching.circuit import N_QUBITS
    need(N_QUBITS==24,'reference_profile_changed')
    return {'job':job,'circuit_sha256':p['circuit_sha256'],'circuit_version':p['circuit_version'],'reference_logical_qubits':N_QUBITS,'reference_source_sha256':sha((root/'quantum/iching/circuit.py').read_bytes()),'evidence':'Recorded job/profile and verified receipt; operator must confirm original circuit matches reference. Not independent QPY reconstruction.'}

def approve_profile(db,job,digest,data,root=ROOT):
    info=review_profile(db,job,data,root);need(info['circuit_sha256']==digest,'digest_confirmation_mismatch')
    evidence='operator_confirmed_recorded_future_profile:'+info['reference_source_sha256']
    db.execute('INSERT OR IGNORE INTO certificate_circuit_profiles VALUES(?,?,?,?,?)',(digest,info['circuit_version'],24,evidence,stamp()))
    row=db.execute('SELECT * FROM certificate_circuit_profiles WHERE circuit_sha256=?',(digest,)).fetchone()
    need(row['logical_qubits']==24 and row['circuit_version']==info['circuit_version'] and row['evidence']==evidence,'profile_conflict')
    return info

def checkpoint_key(data,path):
    key=g.read_key(path);need(g.public_key(key)==(data/'transparency/public/public-key.txt').read_text().strip(),'gqtp_key_mismatch');return key

def find_keys(data):
    result=[]
    for p in (data/'transparency').rglob('*'):
        try:
            if p.is_file() and not p.is_symlink() and p.stat().st_size==32 and p.stat().st_mode&0o077==0:
                checkpoint_key(data,p);result.append(str(p))
        except (ValueError,OSError):pass
    return result

def export_checkpoint(data,env):
    n=env['checkpoint']['tree_size']; dest=data/'transparency/public'/f'checkpoint-{n}.json';raw=g.canonical(env)
    if not dest.exists():
        fd,path=tempfile.mkstemp(prefix='.certificate-checkpoint-',dir=dest.parent)
        try:
            with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            os.chmod(path,0o644)
            try:os.link(path,dest)
            except FileExistsError:pass
        finally:os.unlink(path)
    need(dest.is_file() and not dest.is_symlink() and dest.read_bytes()==raw,'checkpoint_export_mismatch')

def cycle(db,data,key_path,limit=20,root=ROOT):
    need(1<=limit<=100,'bad_limit');key=checkpoint_key(data,key_path)
    # Fair bounded scanning: a failed candidate cannot starve later readings.
    services=tuple(POLICY);params=','.join('?' for _ in services)
    query=ROW_SQL+f''' AND s.service_id IN ({params}) AND (
       NOT EXISTS(SELECT 1 FROM reading_certificates x WHERE x.consultation_id=c.consultation_id)
       OR (EXISTS(SELECT 1 FROM reading_certificates x WHERE x.consultation_id=c.consultation_id AND x.schema_version=?)
           AND NOT EXISTS(SELECT 1 FROM reading_certificates x WHERE x.consultation_id=c.consultation_id AND x.schema_version=?)
           AND EXISTS(SELECT 1 FROM certificate_circuit_profiles p WHERE p.circuit_sha256=json_extract(r.provenance_json,'$.circuit_sha256') AND p.circuit_version=json_extract(r.provenance_json,'$.circuit_version'))))
       ORDER BY COALESCE((SELECT last_attempt FROM certificate_work_attempts a WHERE a.consultation_id=c.consultation_id),''),c.finished_at,c.consultation_id LIMIT ?'''
    rows=db.execute(query,(*services,LEGACY_SCHEMA,SCHEMA,limit)).fetchall(); report=[];pending=[]
    h,r=load_catalog(root);pinned=g.public_key(key)
    for row in rows:
        try:
            state,_=audit_candidate(db,row,g,h,r,pinned)
            if state=='pending_checkpoint':pending.append(row)
            else:report.append(issue(db,row,data,root,apply=True))
        except Exception as exc:report.append({'service':row['service_id'],'state':'blocked','error_type':type(exc).__name__})
        db.execute('INSERT INTO certificate_work_attempts VALUES(?,?) ON CONFLICT(consultation_id) DO UPDATE SET last_attempt=excluded.last_attempt',(row['consultation_id'],stamp()))
    # Signed checkpoints only. No OTS submission/verification/release.
    if pending:
        env=g.checkpoint(db,key);export_checkpoint(data,env)
        for row in pending:
            try:report.append(issue(db,row,data,root,apply=True))
            except Exception as exc:report.append({'service':row['service_id'],'state':'blocked','error_type':type(exc).__name__})
    # Repair an interrupted export, including an existing signed checkpoint.
    latest=db.execute('SELECT envelope_json FROM gqtp_checkpoints ORDER BY tree_size DESC LIMIT 1').fetchone()
    if latest:
        env=json.loads(latest[0]);need(g.verify_checkpoint(env,pinned),'invalid_latest_checkpoint');export_checkpoint(data,env)
    return report
