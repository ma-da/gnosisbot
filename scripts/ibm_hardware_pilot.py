#!/usr/bin/env python3
"""Independent paid QPU pilot; never touches Gnosis database or research counts.

Each manifest is a durable guard against duplicate submission. If submission is
ambiguous (job accepted but ID not returned), operator must reconcile manually.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gnosis_platform.config import get_settings
ALLOWED = ('ibm_marrakesh', 'ibm_fez')
SEEDS = (0,5,8)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def checkpoint(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    data=json.dumps(doc,sort_keys=True,separators=(',',':')).encode()
    fd, name=tempfile.mkstemp(dir=path.parent,prefix='.pilot-')
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        dfd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        if os.path.exists(name):os.unlink(name)


def summary(batch):
    shots=batch['shots']
    agreements=sum(int(s['moving_flag_matches']) for s in shots)
    complete=sum(s['moving_flag_matches']==6 for s in shots)
    return {'n_shots':len(shots),'moving_flag_checks_agree':agreements,
            'moving_flag_checks_total':len(shots)*6,
            'all_six_flags_agree_shots':complete,
            'selected_shot_index':batch['selected_shot_index'],
            'medoid_score':batch['medoid_distance_sums'][batch['selected_shot_index']]}


def main():
    ap=argparse.ArgumentParser(description='Gnosis isolated IBM hardware fidelity pilot; not a consultation')
    ap.add_argument('--directory',default=str(get_settings().data_dir/'ibm-pilots-restricted'))
    sub=ap.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('inspect',help='Compile and print metrics; no QPU submission')
    prep.add_argument('--backend',choices=ALLOWED,required=True)
    prep.add_argument('--seed',type=int,choices=SEEDS,default=5)
    launch=sub.add_parser('submit',help='Run ONE explicitly authorized paid 128-shot job')
    launch.add_argument('--backend',choices=ALLOWED,required=True)
    launch.add_argument('--seed',type=int,choices=SEEDS,default=5)
    launch.add_argument('--pilot-id',required=True,help='Unique safe ID, e.g. fez-seed5-a')
    launch.add_argument('--authorize-paid-hardware',action='store_true')
    fetch=sub.add_parser('collect',help='Retrieve existing known job; never resubmit')
    fetch.add_argument('--pilot-id',required=True)
    args=ap.parse_args()
    directory=Path(args.directory).expanduser().resolve()
    if getattr(args,'pilot_id',None) and (not args.pilot_id.isascii() or not args.pilot_id.replace('-','').replace('_','').isalnum() or len(args.pilot_id)>64):
        ap.error('Pilot ID must be 1-64 alphanumeric, underscore or hyphen characters')
    if args.command=='inspect':
        from gnosis_platform.ibm_worker import snapshot_compiled
        _,_,qc,digest=snapshot_compiled(args.backend,seed=args.seed)
        counts=qc.count_ops()
        print(json.dumps({'backend':args.backend,'seed':args.seed,'shots':128,'compiled_qpy_sha256':digest,
                          'cz':counts.get('cz',0),'full_depth':qc.depth(),
                          'note':'Offline compilation only. No IBM job submitted.'},indent=2))
        return
    manifest=directory/(args.pilot_id+'.json')
    if args.command=='submit':
        if not args.authorize_paid_hardware or os.environ.get('GNOSIS_ENABLE_IBM_PILOT')!='YES':
            ap.error('Submission disabled. Requires GNOSIS_ENABLE_IBM_PILOT=YES and --authorize-paid-hardware')
        if manifest.exists():
            ap.error('Pilot already has a manifest. Refusing duplicate submission; use collect/reconcile.')
        from gnosis_platform.ibm_worker import snapshot_compiled
        _,backend,circuit,digest=snapshot_compiled(args.backend,seed=args.seed)
        doc={'schema':'gnosis.ibm_hardware_pilot.v1','pilot_id':args.pilot_id,
             'backend':args.backend,'seed':args.seed,'shots':128,'circuit_sha256':digest,
             'status':'submission_claimed','claimed_at_utc':stamp(),'ibm_job_id':None}
        # Durable claim MUST precede remote submission. No retry if ID unknown.
        checkpoint(manifest,doc)
        try:
            from qiskit_ibm_runtime import SamplerV2
            job=SamplerV2(mode=backend).run([circuit],shots=128)
            doc.update(status='submitted',ibm_job_id=job.job_id(),submitted_at_utc=stamp())
            checkpoint(manifest,doc)
            print(json.dumps({'status':'submitted','pilot_id':args.pilot_id,'ibm_job_id':doc['ibm_job_id']},indent=2))
        except BaseException:
            print(f'AMBIGUOUS SUBMISSION: {manifest} is claimed. DO NOT rerun submit. Check IBM jobs and reconcile manually.',file=sys.stderr)
            raise
        return
    if not manifest.is_file():
        ap.error(f'No manifest exists: {manifest}')
    doc=json.loads(manifest.read_text())
    if doc.get('status')=='collected':
        print(json.dumps({'status':'collected','pilot_id':doc['pilot_id'],'summary':doc['summary'],'archive':doc['archive']},indent=2));return
    if doc.get('status')!='submitted' or not doc.get('ibm_job_id'):
        ap.error('Cannot retrieve ambiguous claim. Reconcile its IBM job ID manually; never resubmit.')
    from qiskit_ibm_runtime import QiskitRuntimeService
    job=QiskitRuntimeService().job(doc['ibm_job_id'])
    status=str(job.status()).upper()
    if not any(s in status for s in ('DONE','COMPLETED')):
        print(json.dumps({'status':'pending_or_requires_review','ibm_status':status,'pilot_id':doc['pilot_id']},indent=2));return
    from quantum.iching.decoder import analyze_sampler_result
    from quantum.iching.medoid import canonical_payload
    batch=canonical_payload(analyze_sampler_result(job.result(),expected_shots=128))
    data={'schema':'gnosis.ibm_hardware_pilot_result.v1','pilot':doc,'selection':batch,
          'collected_at_utc':stamp(),'statistics':summary(batch)}
    archive=directory/(args.pilot_id+'.result.json')
    if archive.exists():
        ap.error('Existing result file detected. Preserve and manually inspect; not overwriting.')
    checkpoint(archive,data)
    doc.update(status='collected',archive=str(archive),archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),summary=data['statistics'])
    checkpoint(manifest,doc)
    print(json.dumps({'pilot_id':args.pilot_id,'archive':str(archive),'statistics':data['statistics']},indent=2))


if __name__=='__main__':main()
