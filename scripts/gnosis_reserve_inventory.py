#!/usr/bin/env python3
"""Explicit reserve qualification, import, checkpoint and promotion. Never submits hardware."""
import argparse, fcntl, hashlib, json, math, os, sqlite3, sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gnosis_platform import gqtp as g, ibm_inventory, rune_past_inventory as r
from gnosis_platform.db import connect,migrate
from gnosis_platform.certificate_automation import checkpoint_key,export_checkpoint
from gnosis_platform.admin_btc import check
from gnosis_platform.admin_metrics import stamp
DATA=Path('/var/lib/gnosis'); DB=DATA/'gnosis.sqlite3'; BASE=DATA/'ibm-reserve-restricted/initial-20261124'
# Pin operator-observed job IDs and collected raw bytes. Never print measurement records.
PROFILES={
'iching':('dc30k5mq4uuc73a63cp0','470f5aa3a6dea0ae867677c0587dc5e8ff5f5423c1575a6174f7cb46b0308c1c','6e0ebc37ca5cd1ec906e18996ee1143567d8eb4961389eea2f9d88a364559ff4','iching_now_becoming_24q_seed5_v1',256,1,24,256),
'pouch':('dc30ksds2omc738cnvb0','9bd828b73fad10fb501f78de2a409dc4db2ca87cec38af113217179cc6364c39','f987202e9fc45236ca92aae6c6f2786a30ee656d6c23a2fc0f11d465f741a27a','strict-v2a-1.0.0',288,1,15,279),
'sticks':('dc30lhuq4uuc73a63edg','6eb7bec35129243bc6ae9886e1df43e11f800be178cf10619ed4536234376640','45cd8d510fb3fa481c38a93ce0b3417175b2f753cce2622248f3e278c6da6d8e','circular-sticks-1.1.0',4608,18,64,256)}
need=g.require
sha=lambda b:hashlib.sha256(b).hexdigest()
def printj(x):print(json.dumps(x,indent=2),flush=True)
def private_bytes(p):
    need(p.is_file() and not p.is_symlink() and p.stat().st_uid==os.getuid() and p.stat().st_mode&0o077==0,'Unsafe or missing private acquisition file')
    return p.read_bytes()
def archive(mode,base=BASE):
    job,h,qpy,version,shots,group,qubits,valid=PROFILES[mode];d=base/mode
    raw=private_bytes(d/'results.json');need(sha(raw)==h,'Archive digest mismatch')
    doc=json.loads(raw); a=doc['acquisition'];need(a==json.loads(private_bytes(d/'submission.json')),'Acquisition manifest mismatch')
    need(sha(private_bytes(d/'submitted.qpy'))==qpy,'Submitted QPY digest mismatch')
    expected=dict(schema='gnosis.reserve.acquisition.v1',engine=mode,backend='ibm_marrakesh',job_id=job,status='submitted',circuit_sha256=qpy,circuit_version=version,shots=shots,shots_per_casting=group,logical_qubits=qubits)
    need(doc['schema']=='gnosis.reserve.raw.v1' and all(a.get(k)==v for k,v in expected.items()),'Acquisition identity mismatch')
    if mode=='iching':
        review=a['reference_review'];need(review['state']=='match' and review['qiskit_circuit_equality'] is True and review['reference_job']=='dbt5dv7q0h0s73bkc5q0' and review['candidate_qpy_sha256']==qpy,'Missing circuit comparison')
    else:need(a['prior_circuit_sha256']==qpy,'Rune circuit mismatch')
    records=doc['records'];need(len(records)==shots//group,'Wrong casting count')
    if mode=='iching':
        need(all(set(x)=={'coin_bits','moving_qpu_bits'} and len(x['coin_bits'])==18 and len(x['moving_qpu_bits'])==6 and set(x['coin_bits']+x['moving_qpu_bits'])<=set('01') for x in records),'Invalid coin or moving bits')
        count=len(records)
    else:count=sum(r.valid_raw(mode,x) for x in records)
    need(count==valid,'Valid casting count differs')
    meta=dict(mode=mode,backend=a['backend'],external_job_id=job,circuit_sha256=qpy,circuit_version=version,archive_sha256=h,acquired_at=doc['acquired_at'],submitted_at=doc['submitted_at'])
    times=[datetime.fromisoformat(meta[k].replace('Z','+00:00')) for k in ('submitted_at','acquired_at')];need(all(t.tzinfo is not None for t in times) and times[0]<=times[1],'Invalid acquisition times')
    return meta,records

def qualify(mode,svc,base=BASE):
    meta,records=archive(mode,base);job=svc.job(meta['external_job_id']);need(job.job_id()==meta['external_job_id'] and job.backend().name==meta['backend'] and str(job.status()).upper().split('.')[-1] in ('DONE','COMPLETED'),'IBM job identity/status mismatch')
    result=job.result();need(len(result)==1,'Expected one result PUB')
    shots=PROFILES[mode][4]
    if mode=='iching':
        from quantum.iching.decoder import read_sampler_result
        remote=read_sampler_result(result,expected_shots=shots)
    elif mode=='pouch':
        from quantum.pouch.decoder import decode_result
        remote=[x['raw_ranks'] for x in decode_result(result[0])]
    else:
        bits=result[0].data.cast_bits.get_bitstrings();need(len(bits)==shots,'Sticks shots differ');remote=[bits[i:i+18] for i in range(0,len(bits),18)]
    need(remote==records,'IBM measurements differ from archived records')
    metrics=job.metrics();times=metrics['timestamps'];usage=metrics.get('usage') or {}
    need(times['created']==meta['submitted_at'] and times['finished']==meta['acquired_at'],'IBM timestamps differ')
    seconds=usage.get('qpu_charge_time_seconds');need(usage.get('status')=='complete' and type(seconds) in (int,float) and math.isfinite(seconds) and seconds>0,'Final IBM usage missing')
    units=usage.get('value') if usage.get('unit')=='resource_units' else None
    need(units is None or type(units) in (int,float) and math.isfinite(units) and units>=0,'Invalid resource units')
    meta.update(remote_measurements_match=True,qpu_seconds=seconds,resource_units=units)
    return meta,records

def import_one(db,meta,records):
    mode=meta['mode'];job=meta['external_job_id'];need(g.enforced(db),'Inventory enforcement missing')
    bt,it=g.batch_tables(mode);other='rune_inventory_batches' if mode=='iching' else 'ibm_inventory_batches'
    for table,col in ((other,'external_job_id'),('ibm_future_jobs','external_job_id'),('gqtp_live_jobs','job_id')):
        need(not db.execute(f'SELECT 1 FROM {table} WHERE {col}=?',(job,)).fetchone(),'Job already allocated elsewhere')
    need(not db.execute(f"SELECT 1 FROM {bt} WHERE external_job_id=? AND status<>'quarantined'",(job,)).fetchone(),'Job already approved or withdrawn')
    need(not db.execute('SELECT 1 FROM gqtp_batches WHERE job_id=? AND release_checkpoint IS NOT NULL',(job,)).fetchone(),'Job already released')
    db.execute('INSERT OR IGNORE INTO gnosis_reserve_holds(job_id,engine,created_at) VALUES(?,?,?)',(job,mode,stamp()))
    hold=db.execute('SELECT * FROM gnosis_reserve_holds WHERE job_id=?',(job,)).fetchone();need(hold['engine']==mode and hold['promoted_at'] is None,'Reserve already promoted or wrong engine')
    old=db.execute(f'SELECT * FROM {bt} WHERE external_job_id=?',(job,)).fetchall();need(len(old)<=1,'Duplicate job inventory')
    if old:
        b=old[0];bid=b['batch_id'];need(b['status']=='quarantined' and b['item_count']==len(records) and all(b[k]==meta[k] for k in ('backend','circuit_sha256','circuit_version','acquired_at','submitted_at')) and b['source_file_sha256' if mode=='iching' else 'archive_sha256']==meta['archive_sha256'],'Existing inventory mismatch')
    elif mode=='iching':
        m={k:meta[k] for k in ('backend','external_job_id','circuit_sha256','circuit_version','acquired_at','submitted_at')}
        doc=dict(schema='gnosis.ibm_past.v1',manifest=m,samples=[dict(sample_index=i,**x) for i,x in enumerate(records)])
        bid=ibm_inventory.import_archive(db,doc,file_sha256=meta['archive_sha256'])['batch_id']
    else:bid=r.import_batch(db,meta,records)['batch_id']
    rows=db.execute(f'SELECT * FROM {it} WHERE batch_id=? ORDER BY sample_index',(bid,)).fetchall();need(len(rows)==len(records),'Incomplete inventory')
    for i,(row,raw) in enumerate(zip(rows,records)):
        stored={'coin_bits':row['coin_bits'],'moving_qpu_bits':row['moving_qpu_bits']} if mode=='iching' else json.loads(row['raw_json'])
        good=mode=='iching' or r.valid_raw(mode,raw)
        need(row['sample_index']==i and stored==raw and row['consultation_id'] is None and row['state']==('available' if good else 'void'),'Frozen inventory mismatch')
    g.note_qualification(db,bid,meta)
    db.execute('INSERT OR IGNORE INTO gnosis_admin_ibm_usage VALUES(?,?,?,?)',(job,meta['qpu_seconds'],stamp(),'ibm_runtime_final_usage'))
    need(db.execute('SELECT qpu_seconds FROM gnosis_admin_ibm_usage WHERE job_id=?',(job,)).fetchone()[0]==meta['qpu_seconds'],'Existing usage differs')
    if mode=='iching':
        evidence='verified_reserve_job_and_reference_circuit_equality:'+job+':'+meta['archive_sha256']
        db.execute('INSERT OR IGNORE INTO certificate_circuit_profiles VALUES(?,?,?,?,?)',(meta['circuit_sha256'],meta['circuit_version'],24,evidence,stamp()))
        cp=db.execute('SELECT * FROM certificate_circuit_profiles WHERE circuit_sha256=?',(meta['circuit_sha256'],)).fetchone();need(cp['logical_qubits']==24 and cp['circuit_version']==meta['circuit_version'],'Certificate profile conflict')
    b=db.execute('SELECT * FROM gqtp_batches WHERE job_id=?',(job,)).fetchone()
    if not b:g.register_batch(db,mode,bid,confirm_unrevealed=True)
    else:need(b['batch_id']==bid and b['engine']==mode and b['release_checkpoint'] is None,'Existing commitment mismatch')
    groups={x['disposition']:x['n'] for x in db.execute('SELECT disposition,count(*) n FROM gqtp_items WHERE job_id=? GROUP BY disposition',(job,))}
    need(groups.get('commercial')==PROFILES[mode][7] and groups.get('excluded',0)==len(records)-PROFILES[mode][7] and sum(groups.values())==len(records),'Commitment counts mismatch')
    return dict(engine=mode,job_id=job,batch_id=bid,counts=groups,held=True,qpu_seconds=meta['qpu_seconds'],resource_units=meta['resource_units'])

def migrate_only(db):
    actual={x[0] for x in db.execute('SELECT version FROM schema_migrations')};expected={x.name for x in (ROOT/'gnosis_platform/migrations').glob('*.sql')};pending=expected-actual
    need(actual<=expected and pending<={'9015_reserve_holds.sql'},'Unexpected migrations')
    if not pending:return []
    d=DATA/'certificates-private';need(d.is_dir() and not d.is_symlink() and d.stat().st_mode&0o077==0,'Unsafe backup directory')
    dest=d/('pre9015-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite3');fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    with closing(sqlite3.connect(dest)) as out:db.backup(out);need(out.execute('PRAGMA quick_check').fetchone()[0]=='ok','Backup failed')
    print('Backup:',dest,flush=True);return migrate(db)

def main():
    os.umask(0o077);ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('review');sub.add_parser('status')
    for cmd in ('migrate','import','checkpoint','verify','promote'):
        s=sub.add_parser(cmd);s.add_argument('--apply',action='store_true',required=True)
        if cmd=='import':s.add_argument('--confirm-unrevealed',action='store_true',required=True)
        if cmd in ('verify','promote'):s.add_argument('--checkpoint',type=int,required=True)
        if cmd=='promote':s.add_argument('--engine',choices=PROFILES,required=True)
    a=ap.parse_args();need(DB.is_file(),'Missing production DB')
    if a.cmd in ('review','import'):
        from qiskit_ibm_runtime import QiskitRuntimeService
        instance=os.environ.get('GNOSIS_IBM_INSTANCE');need(instance and instance.startswith('crn:'),'Missing IBM CRN');svc=QiskitRuntimeService(instance=instance)
        qualified=[qualify(mode,svc) for mode in PROFILES]
        if a.cmd=='review':printj([{**m,'gross':len(rows),'valid':PROFILES[m['mode']][7]} for m,rows in qualified]);return
    if a.cmd=='status':
        with closing(sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            printj([dict(x) for x in db.execute('SELECT h.*,b.release_checkpoint,(SELECT count(*) FROM gqtp_items i WHERE i.job_id=h.job_id AND i.disposition=\'commercial\') AS commercial FROM gnosis_reserve_holds h LEFT JOIN gqtp_batches b USING(job_id) ORDER BY h.engine')]);return
    with (DATA/'reserve-operations.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with closing(connect(DB)) as db:
            if a.cmd=='migrate':printj(migrate_only(db));return
            need(g.enforced(db),'Inventory guard disabled')
            if a.cmd=='import':
                printj([import_one(db,m,rows) for m,rows in qualified]);return
            if a.cmd=='checkpoint':
                key=checkpoint_key(DATA,DATA/'transparency/signing.key');env=g.checkpoint(db,key);export_checkpoint(DATA,env);n=env['checkpoint']['tree_size'];printj(dict(tree_size=n,path=str(DATA/f'transparency/public/checkpoint-{n}.json')));return
            if a.cmd in ('verify','promote'):
                ots=os.getenv('GNOSIS_OTS_EXECUTABLE',str(Path.home()/'.venvs/opentimestamps/bin/ots'))
                res=check(db,a.checkpoint,DATA/'transparency/public',ots,promote_job=PROFILES[a.engine][0] if a.cmd=='promote' else None);printj(res)
                if res['status']!='bitcoin_verified':sys.exit(2)
if __name__=='__main__':main()
