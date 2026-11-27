#!/usr/bin/env python3
"""Review original qualified I Ching pilot archive and register exact 24q profile.
Never retrieves/submits jobs, changes stock, settles credits or sends mail.
"""
import argparse,json,sqlite3,sys,re
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gnosis_platform import gqtp as g
from gnosis_platform.certificate_validation import need,sha
from gnosis_platform.certificate_store import stamp,ROW_SQL,build_payload,issue
from gnosis_platform.db import connect

def review(db,data,archive,job,root=ROOT):
    b=db.execute('SELECT * FROM ibm_inventory_batches WHERE external_job_id=?',(job,)).fetchall()
    need(len(b)==1,'archive_job_not_unique');b=b[0]
    need(b['status']=='approved' and g.enforced(db),'inventory_not_approved_or_enforced')
    q=db.execute('SELECT metadata_json FROM gqtp_qualifications WHERE batch_id=?',(b['batch_id'],)).fetchone()
    need(q is not None,'qualification_missing');q=json.loads(q[0])
    need(q.get('mode')=='iching' and q.get('remote_measurements_match') is True and q.get('archive_sha256')==b['source_file_sha256'] and all(q.get(k)==b[k] for k in ('external_job_id','backend','circuit_sha256','circuit_version')),'qualification_mismatch')
    raw=archive.read_bytes();need(sha(raw)==b['source_file_sha256'],'original_archive_hash_mismatch')
    a=json.loads(raw);p=a['pilot'];m=json.loads(archive.with_name(archive.name.removesuffix('.result.json')+'.json').read_bytes())
    need(a['schema']=='gnosis.ibm_hardware_pilot_result.v1' and p['status']=='submitted' and m['status']=='collected' and m['archive_sha256']==sha(raw),'pilot_manifest_mismatch')
    need(all(m.get(k)==p.get(k) for k in ('backend','ibm_job_id','circuit_sha256','seed','shots')) and p['ibm_job_id']==job and p['backend']==b['backend'] and p['circuit_sha256']==b['circuit_sha256'],'pilot_job_binding_mismatch')
    need(type(p['seed']) is int and p['seed'] in (0,5,8) and p['shots']==128 and b['circuit_version']==f"iching_now_becoming_24q_seed{p['seed']}_v1",'unrecognized_pilot_profile')
    shots=a['selection']['shots'];need(len(shots)==128==b['item_count'] and all(isinstance(s['coin_bits'],str) and len(s['coin_bits'])==18 and isinstance(s['moving_qpu_bits'],str) and len(s['moving_qpu_bits'])==6 and set(s['coin_bits']+s['moving_qpu_bits'])<=set('01') for s in shots),'pilot_register_shape_mismatch')
    # Compare exact archived sample order to existing frozen inventory, without printing outcomes.
    rows=db.execute('SELECT sample_index,coin_bits,moving_qpu_bits FROM ibm_inventory_items WHERE batch_id=? ORDER BY sample_index',(b['batch_id'],)).fetchall()
    need(len(rows)==len(shots) and all(r[0]==i and r[1]==s['coin_bits'] and r[2]==s['moving_qpu_bits'] for i,(r,s) in enumerate(zip(rows,shots))),'archive_inventory_mismatch')
    gb=db.execute('SELECT * FROM gqtp_batches WHERE job_id=? AND engine=? AND batch_id=?',(job,'iching',b['batch_id'])).fetchone();need(gb is not None and gb['release_checkpoint'] is not None,'release_missing')
    n=gb['release_checkpoint'];cp=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(n,)).fetchone();need(cp is not None,'release_checkpoint_missing');env=json.loads(cp[0]);pub=data/'transparency/public';pinned=(pub/'public-key.txt').read_text().strip();ev=g.events(db,n)
    need(g.verify_checkpoint(env,pinned) and env['checkpoint']['tree_size']==n and g.root([g.leaf(g.canonical(e)) for e in ev]).hex()==env['checkpoint']['root'],'release_checkpoint_invalid')
    need(1<=gb['seq']<=n,'batch_commitment_missing');e=ev[gb['seq']-1];need(e['kind']=='batch_committed' and e['engine']=='iching' and e['ibm_job_id']==job and e['archive_sha256']==sha(raw) and all(e[k]==b[k] for k in ('backend','circuit_sha256','circuit_version')),'signed_batch_mismatch')
    note=json.loads(gb['verification_note']);need(sha((pub/f'checkpoint-{n}.json.ots').read_bytes())==note.get('proof_sha256'),'release_proof_mismatch')
    from quantum.iching.circuit import N_QUBITS
    need(N_QUBITS==24,'reference_profile_changed')
    return {'job':job,'circuit_sha256':b['circuit_sha256'],'circuit_version':b['circuit_version'],'logical_qubits':24,'archive_sha256':sha(raw),'reference_source_sha256':sha((root/'quantum/iching/circuit.py').read_bytes()),'release_checkpoint':n,'evidence':'Original qualified pilot archive, matching stored samples and signed release; operator confirms original logical circuit. No independent QPY reconstruction or fresh Bitcoin verification.'}

def approve(db,info):
    evidence='operator_confirmed_qualified_pilot_archive:'+info['archive_sha256']+':'+info['reference_source_sha256']
    db.execute('INSERT OR IGNORE INTO certificate_circuit_profiles VALUES(?,?,?,?,?)',(info['circuit_sha256'],info['circuit_version'],24,evidence,stamp()))
    r=db.execute('SELECT * FROM certificate_circuit_profiles WHERE circuit_sha256=?',(info['circuit_sha256'],)).fetchone()
    need(r['logical_qubits']==24 and r['circuit_version']==info['circuit_version'],'profile_conflict')

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('command',choices=['review','approve']);a.add_argument('--job',required=True);a.add_argument('--archive',type=Path,default=Path('/var/lib/gnosis/ibm-pilots-restricted/marrakesh-seed5-a.result.json'));a.add_argument('--apply',action='store_true');a.add_argument('--confirm-original-24q',action='store_true');args=a.parse_args()
    if args.command=='approve' and not(args.apply and args.confirm_original_24q):a.error('explicit operator confirmation and --apply required')
    if not args.archive.name.endswith('.result.json'):a.error('expected original pilot .result.json archive')
    path=Path('/var/lib/gnosis/gnosis.sqlite3');data=path.parent
    need(path.is_file(),'production_db_missing')
    if args.command=='review':db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
    else:db=connect(path)
    with closing(db):
        info=review(db,data,args.archive,args.job);print(json.dumps(info,indent=2))
        if args.command=='approve':
            approve(db,info)
            print('Exact circuit profile registered. No email sent.')
if __name__=='__main__':main()
