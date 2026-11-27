#!/usr/bin/env python3
"""Read-only production certificate readiness audit. No provider or email calls."""
import argparse, collections, gzip, hashlib, json, re, sqlite3, sys
from pathlib import Path

POLICY = {'iching.quantum_future':'ibm','iching.quantum_past':'ibm_inventory',
          'iching.qrng_private':'qci'}
for mode in ('pouch','sticks'):
    POLICY.update({f'runes.{mode}.quantum_future':'ibm', f'runes.{mode}.quantum_past':'ibm_inventory', f'runes.{mode}.qrng_private':'qci', f'runes.{mode}.classic':'server_crypto'})

def need(ok, code):
    if not ok: raise ValueError(code)

def sha(b): return hashlib.sha256(b).hexdigest()
def is_hash(s): return isinstance(s,str) and re.fullmatch('[0-9a-f]{64}',s) is not None

def load_catalog(root):
    h=json.loads((root/'app/data/interpretations.json').read_text())['hexagrams']
    r=json.loads((root/'app/data/rune_catalog.json').read_text())
    need(len(h)==64 and {x['number'] for x in h}==set(range(1,65)) and {x['bits'] for x in h}=={f'{i:06b}' for i in range(64)},'invalid_hexagram_catalog')
    need(len(r)==24 and {x['id'] for x in r}==set(range(24)), 'invalid_rune_catalog')
    return {x['bits']:x for x in h}, {x['id']:x for x in r}

def project(service, reading, provenance, hexagrams, runes):
    if service.startswith('iching.'):
        lines=reading.get('lines'); need(isinstance(lines,list) and len(lines)==6 and all(type(v) is int and v in (6,7,8,9) for v in lines),'invalid_lines')
        now=[v%2 for v in lines]; later=[v%2 ^ int(v in (6,9)) for v in lines]; moving=[i+1 for i,v in enumerate(lines) if v in (6,9)]
        for k,v in [('now_yang_bits_bottom_to_top',now),('becoming_yang_bits_bottom_to_top',later),('moving_positions_bottom_to_top',moving)]:
            need(k not in reading or reading[k]==v,'inconsistent_'+k)
        coins=reading.get('coin_bits_bottom_to_top')
        if coins is not None: need(isinstance(coins,list) and len(coins)==6 and all(isinstance(c,str) and len(c)==3 and set(c)<=set('01') and 6+c.count('1')==v for c,v in zip(coins,lines)), 'coin_line_mismatch')
        def hexagram(bits):
            h=hexagrams[''.join(map(str,bits))]; return {'number':h['number'],'title':h['title'],'bits_bottom_to_top':bits}
        return {'format':'iching.v1','lines_bottom_to_top':lines,'now':hexagram(now),'becoming':hexagram(later),'moving_positions':moving}
    mode=service.split('.')[1]; need(reading.get('mode')==mode and reading.get('status')=='ready' and reading.get('delivery') in ('live','precomputed'),'invalid_rune_envelope')
    need(reading.get('provenance')==provenance,'rune_provenance_mismatch')
    def rune(i):
        need(type(i) is int and i in runes,'unknown_rune_id'); return {'rune_id':i,'name':runes[i]['name'],'glyph':runes[i]['glyph']}
    if mode=='pouch':
        draws=reading['payload']['draws']; need(isinstance(draws,list) and len(draws)==3,'invalid_pouch_count')
        out=[]
        for d,pos in zip(draws,('past','present','future')):
            x=rune(d['rune_id']); need(d.get('position')==pos and all(d.get(k)==x[k] for k in ('name','glyph')),'pouch_catalog_mismatch'); out.append({'position':pos,**x})
        need(len({x['rune_id'] for x in out})==3,'duplicate_pouch_rune')
        return {'format':'runes_pouch.v1','draws':out}
    timeline=reading['payload']['timeline']; final=timeline['final']; shown=final['shown']; compounds=final['compounds']
    need(isinstance(shown,dict) and isinstance(compounds,list),'invalid_sticks_frame')
    need(is_hash(provenance.get('profile_sha256')) and timeline['profile_sha256']==provenance['profile_sha256'] and bool(provenance.get('recognition_version')),'recognition_profile_missing')
    need(timeline['frames'][str(timeline['casting_size'])]==final,'inconsistent_final_frame')
    by_name={x['name'].casefold():i for i,x in runes.items()}
    def named(name):
        need(isinstance(name,str) and name.casefold() in by_name,'unknown_sticks_rune'); return rune(by_name[name.casefold()])
    result=[]
    for name,s in shown.items():
        x=named(name); need(s.get('rune')==name and s.get('glyph')==x['glyph'],'sticks_catalog_mismatch'); result.append(x)
    result.sort(key=lambda x:x['rune_id'])
    return {'format':'runes_sticks.v1','recognized':result,'compounds':[[named(n)['name'] for n in c['runes']] for c in compounds], 'recognition_version':provenance['recognition_version']}

def json_replay_equal(rebuilt, stored):
    """Compare JSON data, not Python container types (tuples / integer frame keys).

    Normalize keys before sorting: integer order differs from JSON string order.
    Preserve list order, exact values, and JSON scalar types. No rounding or
    omitted fields. Raw stored reading/provenance/archive hashes are checked
    independently by audit_candidate.
    """
    def normalized(value):
        value=json.loads(json.dumps(value,ensure_ascii=True,allow_nan=False))
        return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)
    return normalized(rebuilt)==normalized(stored)

def audit_candidate(db,row,g,hexagrams,runes,pinned):
    s=row['service_id']; p=json.loads(row['provenance_json']); r=json.loads(row['reading_json']); cid=row['consultation_id']
    need(p.get('provider')==POLICY[s] and p.get('source_quality') not in ('synthetic','simulated','demo'),'source_mismatch')
    need(bool(row['finished_at']),'completion_time_missing')
    projection=project(s,r,p,hexagrams,runes)
    receipt=g.receipt(db,cid); o=receipt['opening']; e=receipt['event']
    need(o['service_id']==s==e['service_id'] and o['reading_schema']==row['schema_version'] and g.commitment(o,receipt['nonce'])==e['commitment'],'receipt_commitment_mismatch')
    need(o['reading_sha256']==sha(row['reading_json'].encode()) and o['provenance_sha256']==sha(row['provenance_json'].encode()),'receipt_saved_bytes_mismatch')
    if s.startswith('runes.'):
        a=db.execute('SELECT archive_sha256,archive_gzip FROM rune_private_archives WHERE consultation_id=?',(cid,)).fetchone()
        need(a is not None and a[0]==o['private_archive_sha256']==sha(gzip.decompress(a[1])),'private_archive_mismatch')
    if receipt['checkpoint']:
        need(pinned and g.verify_receipt(receipt,pinned),'checkpoint_verification_failed')
        state='checkpoint_verified'
    else: state='pending_checkpoint'
    if s.endswith(('.quantum_future','.quantum_past')):
        job=p.get('external_job_id'); need(g.safe_job(job) is not None and e.get('ibm_job_id')==job and is_hash(p.get('circuit_sha256')) and bool(p.get('circuit_version')) and bool(p.get('backend')),'hardware_provenance_missing')
        if s.endswith('.quantum_future'):
            j=db.execute('SELECT * FROM ibm_future_jobs WHERE request_id=?',(row['request_id'],)).fetchone()
            need(j is not None and j['status']=='completed' and all(j[k]==p[k] for k in ('external_job_id','backend','circuit_sha256','circuit_version')) and j['shots']==p.get('n_shots')==({'iching.quantum_future':128,'runes.pouch.quantum_future':1,'runes.sticks.quantum_future':18}[s]) and p.get('source_quality')=='hardware_measurements','future_job_mismatch')
            need(db.execute('SELECT 1 FROM gqtp_live_jobs WHERE job_id=? AND consultation_id=?',(job,cid)).fetchone() is not None,'live_job_binding_missing')
            if s.startswith('iching.'):
                from quantum.iching.medoid import canonical_payload, select_medoid
                selection=p['selection']; shots=selection['shots']; rebuilt=canonical_payload(select_medoid([{'coin_bits':x['coin_bits'],'moving_qpu_bits':x['moving_qpu_bits']} for x in shots],expected_shots=128))
                need(rebuilt==selection and selection['shots'][selection['selected_shot_index']]['values']==r['lines'],'medoid_replay_mismatch')
            else:
                from .future_execution import build_rune,validate_staged_job
                private=json.loads(gzip.decompress(a[1])); staged=private['entropy']
                validate_staged_job(db,row['request_id'],staged,completed_ok=True)
                er,ep,ea=build_rune(s,cid,staged)
                need(json_replay_equal(er,r) and json_replay_equal(ep,p) and json_replay_equal(ea,private),'rune_hardware_replay_mismatch')
        else:
            inv=receipt.get('inventory_receipt'); need(inv is not None and pinned and g.verify_inventory_receipt(inv,pinned),'inventory_receipt_invalid')
            io=inv['opening']; need(io['job_id']==job and io['circuit_sha256']==p['circuit_sha256'] and inv['event']['disposition']=='commercial' and io['measurement_id']==o.get('measurement_id') and g.digest_value(r if s.startswith('iching.') else r['payload'])==io['expected_payload_sha256'],'inventory_payload_mismatch')
            need(db.execute('SELECT 1 FROM gqtp_deliveries WHERE measurement_id=? AND consultation_id=?',(io['measurement_id'],cid)).fetchone() is not None,'delivery_binding_missing')
    return state,projection

