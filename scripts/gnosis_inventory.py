#!/usr/bin/env python3
"""Inspect/import existing IBM archives. Never submits hardware or prints readings."""
import argparse,hashlib,json,math,sys
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.rune_past_inventory import PROFILES,require,import_batch,approve,read_counts,valid_raw
from gnosis_platform.db import connect
from gnosis_platform import ibm_inventory,gqtp
from quantum.pouch.decoder import decode_result,decode_ranks
from quantum.sticks.hardware import REFERENCE_JOB,REFERENCE_HASH,OPTIONS,REGISTER

from gnosis_platform.config import get_settings
DATA=get_settings().data_dir
DEFAULTS={'pouch':DATA/'ibm-inventory-restricted/pouch-production-001', 'sticks':DATA/'ibm-inventory-restricted/sticks-production-001','iching':DATA/'ibm-pilots-restricted/marrakesh-seed5-a.result.json'}

def read(p):return json.loads(p.read_bytes())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load_local(mode,source,qpy=None):
    """Return confidential records and non-secret provenance. No printing."""
    if mode=='pouch':
        qpy=qpy or Path(__file__).resolve().parents[1]/'quantum/pouch/marrakesh.qpy'
        expected,version=PROFILES[mode]
        require(digest(qpy)==expected,'Pouch QPY fingerprint mismatch')
        receipt=read(source/'runes_production_smoke_128_job.json')
        require(receipt['sha256']==expected and receipt['backend']=='ibm_marrakesh' and receipt['shots']==128,'Pouch receipt mismatch')
        jid=receipt['job_id']; require(isinstance(jid,str) and jid.isalnum(),'Invalid job ID')
        path=source/f'runes_production_smoke_{jid}.json'; a=read(path)
        require(all(a[k]==receipt[k] for k in ('job_id','backend','sha256')),'Pouch archive provenance mismatch')
        rows=a['records']; records=[]
        for i,r in enumerate(rows):
            ranks=r['raw_ranks']; good=valid_raw(mode,ranks)
            require(r['shot']==i and r['valid'] is good and r['rune_ids']==decode_ranks(ranks),'Pouch archive decoding mismatch')
            records.append(ranks)
        meta=dict(mode=mode,backend='ibm_marrakesh',external_job_id=jid,circuit_sha256=expected,circuit_version=version,archive_sha256=digest(path))
    elif mode=='sticks':
        expected,version=PROFILES[mode]
        path=source/'results.json'; a=read(path); m=read(source/'manifest.json'); jid=(source/'job_id.txt').read_text().strip()
        require(digest(source/'submitted.qpy')==expected==REFERENCE_HASH and jid==REFERENCE_JOB,'Sticks reference artifact mismatch')
        require(a['manifest']==m and a['job_id']==jid and a['source']=='ibm_qpu','Sticks archive provenance mismatch')
        require(m['backend']=='ibm_marrakesh' and m['sha256']==expected and m['shots']==2304 and m['n_castings']==128 and m['options']==OPTIONS,'Sticks manifest mismatch')
        records=[c['raw_bitstrings_msb_first'] for c in a['castings']]
        for r in records:valid_raw(mode,r)
        meta=dict(mode=mode,backend=m['backend'],external_job_id=jid,circuit_sha256=expected,circuit_version=version,archive_sha256=digest(path))
    else:
        path=source;a=read(path);m=read(path.with_name(path.name.replace('.result.json','.json')))
        require(m['status']=='collected' and m['archive_sha256']==digest(path),'I Ching archive checksum mismatch')
        p=a['pilot'];require(all(m[k]==p[k] for k in ('backend','ibm_job_id','circuit_sha256')),'I Ching manifest mismatch')
        require(a['schema']=='gnosis.ibm_hardware_pilot_result.v1' and p['status']=='submitted','Expected isolated pilot archive')
        records=[{'coin_bits':r['coin_bits'],'moving_qpu_bits':r['moving_qpu_bits']} for r in a['selection']['shots']]
        require(all(len(r['coin_bits'])==18 and len(r['moving_qpu_bits'])==6 and set(r['coin_bits']+r['moving_qpu_bits'])<=set('01') for r in records),'I Ching invalid shot')
        meta=dict(mode=mode,backend=p['backend'],external_job_id=p['ibm_job_id'],circuit_sha256=p['circuit_sha256'],circuit_version=f"iching_now_becoming_24q_seed{p['seed']}_v1",archive_sha256=digest(path))
    require(len(records)==128,'Expected 128 original casting records')
    return meta,records

def verify_remote(meta,records,service):
    """Retrieve existing job only, compare every measured bit in original order."""
    from quantum.iching.decoder import read_sampler_result
    job=service.job(meta['external_job_id']);status=str(job.status()).upper().split('.')[-1]
    require(job.job_id()==meta['external_job_id'] and status in ('DONE','COMPLETED'),'IBM job not completed')
    backend=job.backend();require(backend is not None and backend.name==meta['backend'],'IBM backend mismatch')
    result=job.result();require(len(result)==1,'Unexpected IBM PUB count')
    mode=meta['mode']
    if mode=='pouch':remote=[r['raw_ranks'] for r in decode_result(result[0])]
    elif mode=='sticks':
        raw=getattr(result[0].data,REGISTER).get_bitstrings();require(len(raw)==2304,'IBM sticks shot count mismatch')
        remote=[raw[i:i+18] for i in range(0,len(raw),18)]
    else:remote=read_sampler_result(result,expected_shots=128)
    require(remote==records,'Local archive differs from IBM returned measurements')
    metrics=job.metrics();times=metrics['timestamps'];usage=metrics.get('usage') or {}
    # Actual sample times are not individually reported; use execution finish as batch acquisition marker.
    meta.update(submitted_at=times['created'],acquired_at=times['finished'],acquired_at_basis='IBM job execution finished',running_at=times.get('running'))
    def number(v,positive=False):return v if type(v) in (int,float) and math.isfinite(v) and (v>0 if positive else v>=0) else None
    meta['qpu_seconds']=number(usage.get('qpu_charge_time_seconds'),True) if usage.get('status')=='complete' else None
    meta['resource_units']=number(usage.get('value')) if usage.get('status')=='complete' and usage.get('unit')=='resource_units' else None
    meta['remote_measurements_match']=True
    return meta

def candidate_summary(meta,records,exclude):
    mode=meta['mode'];require(all(0<=i<len(records) for i in exclude),'Excluded indices must be 0..127')
    valid=[True if mode=='iching' else valid_raw(mode,r) for r in records]
    eligible=sum(v and i not in exclude for i,v in enumerate(valid));secs=meta.get('qpu_seconds')
    return {**meta,'attempted':len(records),'invalid':sum(not v for v in valid),'excluded_valid':sum(v and i in exclude for i,v in enumerate(valid)), 'candidate_count':eligible,'qpu_seconds_per_candidate':secs/eligible if secs and eligible else None}

def import_iching(db,meta,records,exclude):
    # Existing I Ching importer only deduplicates by file hash; protect by job ID too.
    if db.execute('SELECT 1 FROM ibm_future_jobs WHERE external_job_id=?',(meta['external_job_id'],)).fetchone() or db.execute('SELECT 1 FROM rune_inventory_batches WHERE external_job_id=?',(meta['external_job_id'],)).fetchone():raise ValueError('Job already allocated to another inventory or live consultation')
    old=db.execute('SELECT batch_id,status FROM ibm_inventory_batches WHERE external_job_id=?',(meta['external_job_id'],)).fetchone()
    if old:
        require(not db.execute('SELECT 1 FROM gqtp_batches WHERE batch_id=?',(old['batch_id'],)).fetchone(),'Already committed; no reimport')
        require(db.execute('SELECT source_file_sha256 FROM ibm_inventory_batches WHERE batch_id=?',(old['batch_id'],)).fetchone()[0]==meta['archive_sha256'],'Existing source mismatch')
        db.executemany("UPDATE ibm_inventory_items SET state='void' WHERE batch_id=? AND sample_index=? AND state='available'",[(old['batch_id'],i) for i in exclude])
        return dict(old)|{'created':False}
    manifest={k:meta[k] for k in ('backend','external_job_id','circuit_sha256','circuit_version','acquired_at','submitted_at')}
    doc={'schema':'gnosis.ibm_past.v1','manifest':manifest,'samples':[{'sample_index':i,**r} for i,r in enumerate(records)]}
    # Source digest anchors the unmodified pilot file; excluded shots remain in that file.
    out=ibm_inventory.import_archive(db,doc,file_sha256=meta['archive_sha256'])
    if out['created']:
        db.executemany("UPDATE ibm_inventory_items SET state='void' WHERE batch_id=? AND sample_index=?",[(out['batch_id'],i) for i in exclude])
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for cmd in ('inspect','import'):
        s=sub.add_parser(cmd);s.add_argument('mode',choices=DEFAULTS);s.add_argument('--source',type=Path);s.add_argument('--qpy',type=Path);s.add_argument('--verify-ibm',action='store_true');s.add_argument('--exclude',type=int,action='append',default=[]);s.add_argument('--confirm-api-stopped',action='store_true')
    s=sub.add_parser('approve');s.add_argument('mode',choices=DEFAULTS);s.add_argument('batch_id');s.add_argument('--operator',required=True);s.add_argument('--job-id',required=True);s.add_argument('--circuit-sha256',required=True);s.add_argument('--confirm-unrevealed',action='store_true')
    sub.add_parser('status');a=p.parse_args()
    if a.command in ('inspect','import'):
        if a.command=='import' and not(a.verify_ibm and a.confirm_api_stopped):p.error('Import requires --verify-ibm and all API/worker processes stopped (--confirm-api-stopped).')
        meta,records=load_local(a.mode,a.source or DEFAULTS[a.mode],a.qpy)
        if a.verify_ibm:
            from qiskit_ibm_runtime import QiskitRuntimeService
            verify_remote(meta,records,QiskitRuntimeService())
        report=candidate_summary(meta,records,set(a.exclude))
        if a.command=='import':
            require(report['candidate_count']>0,'No eligible readings')
            with closing(connect()) as db:
                result=import_iching(db,meta,records,set(a.exclude)) if a.mode=='iching' else import_batch(db,meta,records,excluded=a.exclude)
                report['import']=result
                # Record verified acquisition facts, without publishing outcomes or raw archive.
                gqtp.note_qualification(db,result['batch_id'],meta)
                # Optional dashboard accounting is independent of allocation.
                if meta.get('qpu_seconds') and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gnosis_admin_ibm_usage'").fetchone():
                    from gnosis_platform.admin_metrics import stamp
                    db.execute('INSERT OR IGNORE INTO gnosis_admin_ibm_usage VALUES(?,?,?,?)',(meta['external_job_id'],meta['qpu_seconds'],stamp(),'ibm_runtime_final_usage'))
        print(json.dumps(report,indent=2,default=str));return
    with closing(connect()) as db:
        if a.command=='status':print(json.dumps({'iching':ibm_inventory.inventory_counts(db),'runes':read_counts(db)},indent=2));return
        require(a.confirm_unrevealed,'Must explicitly confirm previously revealed/reserved readings were excluded before import')
        require(gqtp.enforced(db),'Enable GQTP inventory enforcement before approval')
        require(db.execute('SELECT 1 FROM gqtp_batches WHERE batch_id=? AND release_checkpoint IS NOT NULL',(a.batch_id,)).fetchone(),'Batch requires verified checkpoint release')
        if a.mode=='iching':ibm_inventory.approve_batch(db,a.batch_id,operator=a.operator,verified_job_id=a.job_id,verified_circuit_sha256=a.circuit_sha256)
        else:approve(db,a.batch_id,operator=a.operator,job_id=a.job_id,profile_sha=a.circuit_sha256,confirm_unrevealed=True)
        print(json.dumps({'batch_id':a.batch_id,'status':'approved'}))
if __name__=='__main__':main()
