"""Operator-controlled single-reading IBM Future execution. No timers or retries."""
from pathlib import Path
import hashlib, io, json, math, os
from .ibm_future_queue import mark_submitted, stamp
from .rune_services import SCHEMA
from .future_trial import SERVICES

ROOT=Path(__file__).resolve().parents[1]
PROFILES={
 'iching.quantum_future':('quantum/iching/preflight.qpy','6e0ebc37ca5cd1ec906e18996ee1143567d8eb4961389eea2f9d88a364559ff4','iching_now_becoming_24q_seed5_v1',128,24),
 'runes.pouch.quantum_future':('quantum/pouch/marrakesh.qpy','f987202e9fc45236ca92aae6c6f2786a30ee656d6c23a2fc0f11d465f741a27a','strict-v2a-1.0.0',1,15),
 'runes.sticks.quantum_future':('quantum/sticks/marrakesh.qpy','45cd8d510fb3fa481c38a93ce0b3417175b2f753cce2622248f3e278c6da6d8e','circular-sticks-1.1.0',18,64)}
BACKEND='ibm_marrakesh'
def need(ok,msg):
    if not ok: raise ValueError(msg)
def compact(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(x): return hashlib.sha256(x).hexdigest()
def job_row(db,rid):
    row=db.execute('''SELECT j.*,r.service_id,r.status AS request_status,r.credits_cost,r.consultation_id,a.is_admin,a.status AS account_status
      FROM ibm_future_jobs j JOIN service_requests r USING(request_id) JOIN consultations c USING(consultation_id) JOIN accounts a USING(account_id) WHERE j.request_id=?''',(rid,)).fetchone()
    need(row is not None and row['service_id'] in SERVICES and row['credits_cost']==10,'Unknown funded Future request');return row

def load_circuit(service):
    from qiskit import qpy
    path,sha,version,shots,qubits=PROFILES[service];raw=(ROOT/path).read_bytes()
    need(digest(raw)==sha,'Qualified QPY digest mismatch');circuits=qpy.load(io.BytesIO(raw));need(len(circuits)==1,'Expected one circuit');qc=circuits[0]
    if service=='iching.quantum_future':need({r.name:r.size for r in qc.cregs}=={'coins':18,'moves':6},'I Ching register mapping mismatch')
    elif service.endswith('pouch.quantum_future'):
        from quantum.pouch.smoke_test import load_verified
        need(qc==load_verified(ROOT/path),'Pouch verification mismatch')
    else:
        from quantum.sticks.hardware import measurement_map,verify_isa
        verify_isa(qc,measurement_map(qc))
    return qc

def runtime():
    from qiskit_ibm_runtime import QiskitRuntimeService
    return QiskitRuntimeService(instance=os.environ['GNOSIS_IBM_INSTANCE'])

def production_request(db,rid):
    r=db.execute('SELECT permit_id FROM future_auto_requests WHERE request_id=?',(rid,)).fetchone()
    return r is not None and r['permit_id'] is None

def eligible_owner(db,row):
    return row['account_status']=='active' and (row['is_admin'] or production_request(db,row['request_id']))

def claim(db,rid,*,automatic=False):
    db.execute('BEGIN IMMEDIATE')
    try:
        row=job_row(db,rid)
        need(row['status']=='queued' and row['request_status']=='pending' and eligible_owner(db,row),'Request is not an active funded Future request')
        from .future_auto_policy import claim_permit
        claim_permit(db,rid,automatic)
        # Each explicitly authorized request has its own sticky claim.
        t=stamp();need(db.execute("UPDATE ibm_future_jobs SET status='submitting',submit_claimed_at=?,updated_at=? WHERE request_id=? AND status='queued'",(t,t,rid)).rowcount==1,'Claim lost');db.commit()
    except Exception:db.rollback();raise

def submit(db,rid,*,authorized=False,remaining=0,automatic=False):
    from .future_auto_policy import enabled as auto_enabled, production_enabled
    production=automatic and production_request(db,rid)
    need(authorized and (auto_enabled() if automatic else os.getenv('GNOSIS_ENABLE_IBM_LIVE_SUBMISSION')=='YES') and (production_enabled() if production else (math.isfinite(remaining) and remaining>=20)),'Paid submission not authorized')
    row=job_row(db,rid);need(row['status']=='queued' and row['request_status']=='pending' and eligible_owner(db,row),'Not queued funded Future request')
    service=row['service_id'];path,sha,version,shots,qubits=PROFILES[service]
    if service.startswith('iching.'):
        need(db.execute('SELECT 1 FROM certificate_circuit_profiles WHERE circuit_sha256=? AND circuit_version=? AND logical_qubits=24',(sha,version)).fetchone(),'Qualified I Ching certificate profile missing')
    qc=load_circuit(service);svc=runtime();backend=svc.backend(BACKEND);need(backend.name==BACKEND and backend.status().operational,'Backend unavailable')
    for inst in qc.data:
        args=tuple(qc.find_bit(q).index for q in inst.qubits)
        need(backend.target.instruction_supported(operation_name=inst.operation.name,qargs=args),'Native instruction no longer supported')
    if service.startswith('iching.'):
        from qiskit_ibm_runtime import SamplerV2
        sampler=SamplerV2(mode=backend);options={'selection':'iching_global_medoid_weighted_lines_v1'}
    else:
        from qiskit_ibm_runtime.executor_sampler import Sampler
        sampler=Sampler(mode=backend);sampler.options.twirling.enable_gates=False;sampler.options.twirling.enable_measure=False;sampler.options.dynamical_decoupling.enable=False
        options={'gate_twirling':False,'measurement_twirling':False,'dynamical_decoupling':False}
        if service.endswith('pouch.quantum_future'):sampler.options.execution.init_qubits=True;options['init_qubits']=True
    # Sticky claim before the only paid call. Never retry an ambiguous submission.
    claim(db,rid,automatic=automatic)
    job=sampler.run([qc],shots=shots);jid=job.job_id()
    mark_submitted(db,rid,external_job_id=jid,backend=BACKEND,circuit_sha256=sha,circuit_version=version,shots=shots,metadata={'trial':True,'options':options,'logical_qubits':qubits,'operator_remaining_seconds':remaining})
    return dict(request_id=rid,service_id=service,external_job_id=jid,shots=shots,status='submitted')

def verify_remote(row,job):
    need(job.job_id()==row['external_job_id'] and job.backend().name==row['backend']==BACKEND,'Remote IBM identity mismatch')
    # IBM 0.52.1 returned deserialized QuantumProgram objects in production.
    inputs=job.inputs;program=inputs.get('quantum_program');items=getattr(program,'items',None)
    qc=load_circuit(row['service_id'])
    if items is not None:
        items=list(items);need(len(items)==1 and type(items[0]).__name__=='CircuitItem' and getattr(items[0],'circuit',None)==qc and getattr(program,'shots',None)==row['shots'],'Remote circuit or shot count mismatch')
    else:
        pubs=inputs.get('pubs');need(isinstance(pubs,(list,tuple)) and len(pubs)==1,'Remote input format not recognized')
        pub=pubs[0];remote=getattr(pub,'circuit',None);shots=getattr(pub,'shots',None)
        if isinstance(pub,(list,tuple)) and pub:remote=pub[0];shots=pub[2] if len(pub)>2 else None
        need(remote==qc and shots==row['shots'],'Remote circuit or shot count mismatch')

def decode_rune(mode,result):
    need(len(result)==1,'Expected one result PUB')
    if mode=='pouch':
        from quantum.pouch.decoder import decode_result
        rows=decode_result(result[0]);need(len(rows)==1,'Expected exactly one Pouch shot');return rows[0]['raw_ranks']
    bits=result[0].data.cast_bits.get_bitstrings();need(len(bits)==18,'Expected exactly 18 Sticks shots');return bits

def staged_payload(row,raw):
    return {'schema':'gnosis.rune_future.raw.v1','raw':raw,'provenance':{'provider':'ibm','external_job_id':row['external_job_id'],'backend':row['backend'],'circuit_sha256':row['circuit_sha256'],'circuit_version':row['circuit_version'],'n_shots':row['shots'],'submitted_at':row['submitted_at'],'source_quality':'hardware_measurements','raw_sha256':digest(compact(raw).encode()),'fallback_used':False,'qpu_circuit_executed':True}}

def validate_staged_job(db,rid,staged,completed_ok=False):
    row=job_row(db,rid);need(row['service_id'].startswith('runes.') and row['status'] in (('result_ready','completed') if completed_ok else ('result_ready',)),'Rune Future job not staged')
    need(staged==staged_payload(row,staged['raw']),'Staged hardware provenance mismatch')
    _,sha,ver,shots,_=PROFILES[row['service_id']];need((row['backend'],row['circuit_sha256'],row['circuit_version'],row['shots'])==(BACKEND,sha,ver,shots),'Unqualified hardware profile')
    metadata=json.loads(row['metadata_json'] or '{}');need(metadata.get('result_sha256')==digest(compact(staged).encode()),'Staged archive hash mismatch')

def build_rune(service,cid,stage):
    from .rune_past_inventory import valid_raw
    from .rune_oracle_adapter import pouch_payload,sticks_payload
    mode=service.split('.')[1];p=dict(stage['provenance']);raw=stage['raw'];_,sha,ver,shots,_=PROFILES[service]
    need(p['provider']=='ibm' and p['backend']==BACKEND and (p['circuit_sha256'],p['circuit_version'],p['n_shots'])==(sha,ver,shots) and p['raw_sha256']==digest(compact(raw).encode()) and valid_raw(mode,raw),'Invalid measured rune casting')
    decoded=pouch_payload(raw) if mode=='pouch' else sticks_payload(raw)
    if mode=='pouch':p['engine_version']='ordered-rank-decoder-v1'
    else:p.update(recognition_version=decoded['recognition_version'],profile_sha256=decoded['profile_sha256'])
    reading={'schema_version':SCHEMA,'reading_id':cid,'mode':mode,'source':'ibm_qpu','delivery':'live','status':'ready','provenance':p,'payload':decoded['payload']}
    return reading,p,{'entropy':stage,'audit':decoded['private_audit']}

def stage_rune(db,rid,result):
    row=job_row(db,rid);need(row['status'] in ('submitted','running','result_ready') and row['service_id'].startswith('runes.'),'Expected submitted rune job')
    mode=row['service_id'].split('.')[1];raw=decode_rune(mode,result);stage=staged_payload(row,raw)
    from .rune_past_inventory import valid_raw
    valid=valid_raw(mode,raw)
    db.execute('BEGIN IMMEDIATE')
    try:
        row=job_row(db,rid);need(row['status'] in ('submitted','running','result_ready') and stage==staged_payload(row,raw),'Job changed')
        existing=db.execute('SELECT * FROM rune_executions WHERE request_id=?',(rid,)).fetchone()
        if existing:need(existing['status']=='staged' and existing['staged_json']==compact(stage),'Stored result conflicts')
        else:db.execute("INSERT INTO rune_executions(request_id,status,created_at,staged_json,updated_at) VALUES(?,'staged',?,?,?)",(rid,stamp(),compact(stage),stamp()))
        metadata=json.loads(row['metadata_json'] or '{}');metadata.update(result_sha256=digest(compact(stage).encode()),decoder_valid=valid)
        db.execute("UPDATE ibm_future_jobs SET status='result_ready',metadata_json=?,updated_at=? WHERE request_id=?",(compact(metadata),stamp(),rid));db.commit()
    except Exception:db.rollback();raise
    return {'status':'result_ready','request_id':rid,'decoder_valid':valid}

def usage(db,rid,job):
    metrics=job.metrics();u=metrics.get('usage') or {};final=u.get('status')=='complete';q=u.get('qpu_charge_time_seconds') if final else None;ru=u.get('value') if final and u.get('unit')=='resource_units' else None
    # Usage metric is not invoice/billing time. Missing values are not fabricated.
    for v in (q,ru):need(v is None or (type(v) in (int,float) and math.isfinite(v) and v>=0),'Invalid provider usage')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=job_row(db,rid);meta=json.loads(row['metadata_json'] or '{}');new={'qpu_charge_time_seconds':q,'resource_units':ru,'usage_final':final,'timestamps':metrics.get('timestamps'),'observed_at':stamp()}
        if meta.get('provider_usage',{}).get('usage_final') and not final:
            db.commit();return meta['provider_usage']
        meta['provider_usage']=new
        db.execute('UPDATE ibm_future_jobs SET metadata_json=? WHERE request_id=?',(compact(meta),rid))
        if q is not None:db.execute('INSERT INTO gnosis_admin_ibm_usage(job_id,qpu_seconds,observed_at,source) VALUES(?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET qpu_seconds=excluded.qpu_seconds,observed_at=excluded.observed_at,source=excluded.source',(row['external_job_id'],q,stamp(),'ibm_job_metrics'))
        db.commit()
    except Exception:db.rollback();raise
    return meta['provider_usage']

def fail_job(db,rid,code):
    from .transactions import finish_request
    row=job_row(db,rid);need(row['request_status'] in ('pending','failed'),'Cannot fail a settled successful reading')
    finish_request(db,rid,success=False)
    db.execute("UPDATE ibm_future_jobs SET status='failed',failure_code=?,updated_at=?,finished_at=? WHERE request_id=? AND status IN ('submitted','running','result_ready','failed')",(code,stamp(),stamp(),rid))
    return {'status':'failed','reason':code,'request_id':rid,'credits_refunded':10}

def retrieve_rune(db,rid):
    row=job_row(db,rid);need(row['service_id'].startswith('runes.') and row['status'] in ('submitted','running','result_ready'),'Not retrievable')
    if row['status']=='result_ready':return {'status':'result_ready','request_id':rid}
    job=runtime().job(row['external_job_id']);status=str(job.status()).upper().split('.')[-1]
    need(job.job_id()==row['external_job_id'] and job.backend().name==row['backend'],'Remote job mismatch')
    if status in ('ERROR','FAILED','CANCELLED','CANCELED'):
        out=fail_job(db,rid,'ibm_'+status.lower());out['usage']=usage(db,rid,job);return out
    if status not in ('DONE','COMPLETED'):return {'status':'pending','ibm_status':status}
    verify_remote(row,job);out=stage_rune(db,rid,job.result());out['usage']=usage(db,rid,job);return out

def settle_rune(db,rid):
    from .transactions import finish_request
    from .reading_completion import wake_for
    row=job_row(db,rid);need(row['status'] in ('result_ready','completed','failed'),'Rune job not ready')
    if row['request_status']=='failed':return fail_job(db,rid,row['failure_code'] or 'invalid_measured_ranks')
    if row['request_status']!='completed':
        entry=db.execute('SELECT staged_json FROM rune_executions WHERE request_id=?',(rid,)).fetchone();need(entry is not None and entry[0] is not None,'Missing staged measurements')
        stage=json.loads(entry[0]);validate_staged_job(db,rid,stage)
        from .rune_past_inventory import valid_raw
        if not valid_raw(row['service_id'].split('.')[1],stage['raw']):return fail_job(db,rid,'invalid_measured_ranks')
        reading,p,private=build_rune(row['service_id'],row['consultation_id'],stage)
        finish_request(db,rid,success=True,result_json=reading,provenance_json=p,schema_version=SCHEMA,private_rune_archive=private)
    db.execute("UPDATE ibm_future_jobs SET status='completed',finished_at=?,updated_at=? WHERE request_id=? AND status='result_ready'",(stamp(),stamp(),rid));wake_for(db)
    return {'status':'completed','request_id':rid,'replayed':row['request_status']=='completed'}

def retrieve(db,rid,spool):
    row=job_row(db,rid)
    if row['service_id'].startswith('runes.'):return retrieve_rune(db,rid)
    if row['status']=='result_ready':return {'status':'result_ready','request_id':rid}
    need(row['status'] in ('submitted','running'),'Not retrievable');job=runtime().job(row['external_job_id']);status=str(job.status()).upper().split('.')[-1]
    need(job.job_id()==row['external_job_id'] and job.backend().name==row['backend'],'Remote job mismatch')
    if status in ('ERROR','FAILED','CANCELLED','CANCELED'):
        out=fail_job(db,rid,'ibm_'+status.lower());out['usage']=usage(db,rid,job);return out
    if status not in ('DONE','COMPLETED'):return {'status':'pending','ibm_status':status}
    verify_remote(row,job)
    from .ibm_worker import stage_result
    out=stage_result(db,rid,result=job.result(),spool=spool);out['usage']=usage(db,rid,job);return out

def record_billing(db,rid,seconds,*,replace_expected=None,reason=None):
    need(math.isfinite(seconds) and seconds>=0,'Invalid billed seconds');row=job_row(db,rid);need(row['status'] in ('completed','failed') and row['external_job_id'],'Job not final')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=job_row(db,rid);meta=json.loads(row['metadata_json'] or '{}');prior=meta.get('operator_billing')
        if replace_expected is not None:
            need(prior is not None and prior['billed_seconds']==replace_expected and isinstance(reason,str) and 0<len(reason.strip())<=500,'Correction requires matching prior seconds and reason')
        if prior is not None and prior['billed_seconds']!=seconds:
            need(replace_expected is not None,'Existing billing observation differs; specify explicit correction')
            meta.setdefault('operator_billing_history',[]).append({'previous':prior,'replacement_seconds':seconds,'reason':reason.strip(),'corrected_at':stamp()})
        if prior is None or prior['billed_seconds']!=seconds:
            meta['operator_billing']={'billed_seconds':seconds,'source':'operator IBM billing interface','recorded_at':stamp()}
            db.execute('UPDATE ibm_future_jobs SET metadata_json=? WHERE request_id=?',(compact(meta),rid))
        db.commit()
    except Exception:db.rollback();raise
    return meta['operator_billing']
