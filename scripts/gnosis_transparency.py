#!/usr/bin/env python3
"""Local operator CLI; no QPU, credits, payment, or email actions."""
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform import gqtp as g
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect

def atomic(path,data,private=False):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.gqtp-')
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600 if private else 0o644);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def immutable(path,data):
    path=Path(path)
    if path.exists():g.require(path.read_bytes()==data,'Existing exported file differs: '+str(path))
    else:atomic(path,data)
def show(o):print(json.dumps(o,indent=2))
def load(p):return json.loads(Path(p).read_bytes())
def export(db,directory,envelope):
    n=envelope['checkpoint']['tree_size'];directory=Path(directory);f=directory/f'checkpoint-{n}.json'
    immutable(f,g.canonical(envelope));ev=g.events(db,n)
    immutable(directory/f'events-{n}.jsonl',b''.join(g.canonical(e)+b'\n' for e in ev))
    immutable(directory/'public-key.txt',(envelope['checkpoint']['public_key']+'\n').encode('ascii'))
    # Latest pointer is mutable; signed files + historical snapshots are not.
    atomic(directory/'latest.json',g.canonical({'tree_size':n,'checkpoint':f.name,'events':f'events-{n}.jsonl'}))
    return f

def main():
    config=get_settings();base=config.data_dir/'transparency';p=argparse.ArgumentParser(description=__doc__);p.add_argument('--key',type=Path,default=base/'signing.key');p.add_argument('--export-dir',type=Path,default=base/'public');p.add_argument('--ots',default='ots');sub=p.add_subparsers(dest='cmd',required=True)
    for c in ('init-key','status','backfill','checkpoint','enforce-inventory'):sub.add_parser(c)
    for c in ('stamp','upgrade'):
        a=sub.add_parser(c);a.add_argument('tree_size',type=int)
    a=sub.add_parser('register-batch');a.add_argument('engine',choices=['iching','pouch','sticks']);a.add_argument('batch_id');a.add_argument('--demo-count',type=int,default=0);a.add_argument('--exclude',type=int,action='append',default=[]);a.add_argument('--confirm-unrevealed',action='store_true')
    a=sub.add_parser('release-batch');a.add_argument('job_id');a.add_argument('tree_size',type=int);a.add_argument('--operator',required=True)
    a=sub.add_parser('receipt');a.add_argument('consultation_id');a.add_argument('--out',type=Path,required=True)
    a=sub.add_parser('verify-receipt');a.add_argument('file',type=Path);a.add_argument('--public-key',required=True)
    a=sub.add_parser('verify-log');a.add_argument('checkpoint',type=Path);a.add_argument('events',type=Path);a.add_argument('--public-key',required=True);a.add_argument('--previous',type=Path)
    args=p.parse_args();os.umask(0o077)
    if args.cmd=='verify-receipt':
        if not g.verify_receipt(load(args.file),args.public_key):p.exit(1,'FAIL\n')
        print('PASS: commitment, saved bytes, inclusion and pinned signature (not IBM origin or Bitcoin verification)');return
    if args.cmd=='verify-log':
        env=load(args.checkpoint);ev=[json.loads(s) for s in args.events.read_text().splitlines()];c=env['checkpoint'];leaves=[g.leaf(g.canonical(e)) for e in ev]
        g.require(g.verify_checkpoint(env,args.public_key) and len(ev)==c['tree_size'] and all(e['seq']==i for i,e in enumerate(ev,1)) and g.root(leaves).hex()==c['root'],'Log verification failed')
        if args.previous:
            old=load(args.previous);o=old['checkpoint'];g.require(g.verify_checkpoint(old,args.public_key) and o['tree_size']<=len(ev) and g.root(leaves[:o['tree_size']]).hex()==o['root'],'Inconsistent previously witnessed prefix')
        print('PASS: signed log and requested earlier prefix');return
    with closing(connect()) as db:
        if args.cmd=='init-key':
            g.require(not db.execute('SELECT 1 FROM gqtp_checkpoints').fetchone(),'Checkpoints exist: restore original key; do not rotate silently');pk=g.new_key(args.key);show({'public_key':pk,'fingerprint_sha256':g.hx(bytes.fromhex(pk))});return
        if args.cmd=='status':
            show({'events':db.execute('SELECT count(*) FROM gqtp_events').fetchone()[0],'receipts':db.execute('SELECT count(*) FROM gqtp_receipts').fetchone()[0],'unregistered_completed':db.execute("SELECT count(*) FROM reading_results r JOIN consultations c USING(consultation_id) WHERE c.status='completed' AND NOT EXISTS(SELECT 1 FROM gqtp_receipts q WHERE q.consultation_id=c.consultation_id)").fetchone()[0],'inventory_enforced':g.enforced(db),'checkpoint_sizes':[r[0] for r in db.execute('SELECT tree_size FROM gqtp_checkpoints ORDER BY tree_size')],'batches':[dict(r) for r in db.execute('SELECT job_id,engine,batch_id,release_checkpoint FROM gqtp_batches')]});return
        if args.cmd=='backfill':show({'historical_backfill_count':g.backfill(db)});return
        if args.cmd=='enforce-inventory':g.enable_inventory_guard(db);print('Inventory release enforcement enabled');return
        if args.cmd=='register-batch':show(g.register_batch(db,args.engine,args.batch_id,demo_count=args.demo_count,excluded=args.exclude,confirm_unrevealed=args.confirm_unrevealed));return
        if args.cmd=='checkpoint':
            f=export(db,args.export_dir,g.checkpoint(db,g.read_key(args.key)));print(f);return
        if args.cmd=='receipt':
            g.require(not args.out.exists(),'Refusing to overwrite receipt');atomic(args.out,g.canonical(g.receipt(db,args.consultation_id)),private=True);print('Private receipt written:',args.out);return
        n=args.tree_size;row=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(n,)).fetchone();g.require(row,'Unknown checkpoint');env=json.loads(row[0]);f=args.export_dir/f'checkpoint-{n}.json';ots=f.with_suffix('.json.ots');g.require(f.is_file() and f.read_bytes()==g.canonical(env),'Signed checkpoint file mismatch; export original first')
        if args.cmd=='stamp':
            if ots.exists():print('Existing proof preserved; use upgrade');return
            subprocess.run([args.ots,'stamp',str(f)],check=True,timeout=120);print('Submitted timestamp; not independently confirmed');return
        g.require(ots.is_file(),'Missing .ots proof')
        if args.cmd=='upgrade':
            if db.execute('SELECT 1 FROM gqtp_batches WHERE release_checkpoint=?',(n,)).fetchone():print('Verified release proof preserved');return
            subprocess.run([args.ots,'upgrade',str(ots)],check=True,timeout=120);print('Upgrade attempted; confirmation is not asserted');return
        if args.cmd=='release-batch':
            # Snapshot exact bytes before checking. No unsafe skip-verification option.
            from tempfile import TemporaryDirectory
            digest=g.hx(ots.read_bytes())
            with TemporaryDirectory() as tmp:
                tf=Path(tmp)/f.name;tf.write_bytes(f.read_bytes());tp=tf.with_suffix('.json.ots');tp.write_bytes(ots.read_bytes());g.require(g.hx(tp.read_bytes())==digest,'Proof changed')
                subprocess.run([args.ots,'verify',str(tp)],check=True,timeout=180)
            g.require(g.hx(ots.read_bytes())==digest,'Proof changed after verification');g.release_batch(db,args.job_id,n,proof_sha256=digest,operator=args.operator);print('Verified release registered; normal operator approval still required')
if __name__=='__main__':main()
