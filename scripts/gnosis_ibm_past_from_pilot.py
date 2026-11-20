#!/usr/bin/env python3
"""Offline converter: a verified, collected IBM pilot -> quarantinable IBM Past batch.

Never imports, approves, charges or contacts IBM. Uses the existing M4A schema.
The pilot collector timestamp is NOT necessarily the physical acquisition time.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gnosis_platform.ibm_inventory import validate_archive


def convert_pilot(result, *, acquired_at):
    pilot=result['pilot']
    if result.get('schema')!='gnosis.ibm_hardware_pilot_result.v1' or pilot.get('status')!='submitted':
        # Embedded manifest is submitted even when surrounding on-disk manifest
        # has since become 'collected'.
        raise ValueError('Expected original submitted IBM pilot result')
    selection=result['selection'];shots=selection['shots']
    if len(shots)!=128 or not all(isinstance(s.get('coin_bits'),str) and len(s['coin_bits'])==18
                                  and set(s['coin_bits'])<=set('01')
                                  and isinstance(s.get('moving_qpu_bits'),str)
                                  and len(s['moving_qpu_bits'])==6
                                  and set(s['moving_qpu_bits'])<=set('01') for s in shots):
        raise ValueError('Incomplete IBM pilot 128-shot coin archive')
    manifest={'backend':pilot['backend'],'external_job_id':pilot['ibm_job_id'],
              'circuit_sha256':pilot['circuit_sha256'],
              'circuit_version':f"iching_now_becoming_24q_seed{pilot['seed']}_v1",
              'acquired_at':acquired_at,'submitted_at':pilot['submitted_at_utc']}
    doc={'schema':'gnosis.ibm_past.v1','manifest':manifest,
         'samples':[{'sample_index':i,'coin_bits':s['coin_bits'],
                    'moving_qpu_bits':s['moving_qpu_bits']} for i,s in enumerate(shots)]}
    return validate_archive(doc)


def main():
    p=argparse.ArgumentParser(description='Prepare quarantine archive from an isolated IBM QPU pilot')
    p.add_argument('pilot_result',type=Path)
    p.add_argument('--acquired-at',required=True,
        help='Timezone-qualified verified acquisition timestamp; do NOT substitute collection time without disclosure')
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    raw=args.pilot_result.read_bytes()
    source=json.loads(raw)
    manifest_path=args.pilot_result.with_name(args.pilot_result.name.replace('.result.json','.json'))
    if not manifest_path.is_file():p.error('Expected matching original pilot manifest next to result')
    m=json.loads(manifest_path.read_text())
    if m.get('status')!='collected' or m.get('archive_sha256')!=hashlib.sha256(raw).hexdigest():
        p.error('Collected manifest checksum mismatch: original archive needs operator reconciliation')
    if any(m.get(k)!=source['pilot'].get(k) for k in ('ibm_job_id','backend','circuit_sha256')):
        p.error('Pilot manifest does not match embedded immutable job metadata')
    document=convert_pilot(source,acquired_at=args.acquired_at)
    path=args.output.expanduser().resolve()
    if path.exists():p.error('Refusing to overwrite existing archive')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as out:
        json.dump(document,out,indent=2,ensure_ascii=False)
        out.write('\n')
    print(json.dumps({'archive':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'samples':len(document['samples']),'status':'not_imported_or_approved',
                      'warning':'Human-verify IBM job, circuit and physical measurement time before approval.'},indent=2))
if __name__=='__main__':main()
