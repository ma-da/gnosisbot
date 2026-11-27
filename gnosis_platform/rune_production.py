"""Genuine synchronous rune sources. Claim once, stage once, settle atomically.
Never retry an ambiguous provider call or discard a valid empty sticks casting.
"""
import gzip, hashlib, json, secrets, time
from datetime import datetime,timezone
from . import qci_qrng,nist_beacon
from .identity import iso,now
from .rune_services import SCHEMA,spec
from .rune_oracle_adapter import pouch_payload,sticks_payload


def packed(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def pouch_ranks(raw):
    # Stream consecutive MSB-first 5-bit groups; discard only out-of-range ranks.
    bits=''.join(f'{x:08b}' for x in raw)
    ranks=[]; tried=[]
    for i in range(0,len(bits)-4,5):
        rank=int(bits[i:i+5],2); tried.append(rank)
        if rank < (24,23,22)[len(ranks)]: ranks.append(rank)
        if len(ranks)==3: return ranks,tried
    raise ValueError('Entropy budget exhausted before three valid ranks')


def acquire(service_id,request_id):
    mode,source,provider=spec(service_id)
    count=24 if mode=='pouch' else 144
    started=time.perf_counter()
    if provider=='server_crypto':
        raw=secrets.token_bytes(count)
        provenance={'provider':provider,'entropy_source':'Python secrets.token_bytes / OS CSPRNG'}
    elif provider=='qci':
        n=count//2
        samples=qci_qrng._post(qci_qrng._RANDOM,{'distribution':'uniform_discrete',
            'output_type':'decimal','n_samples':n,'n_bits':16},bearer=qci_qrng._access_token())
        if not isinstance(samples,list) or len(samples)!=n or any(type(x) is not int or not 0<=x<65536 for x in samples):
            raise ValueError('Invalid QCI response')
        raw=b''.join(x.to_bytes(2,'big') for x in samples)
        provenance={'provider':'qci','service':'uqrng','endpoint':qci_qrng._RANDOM,
             'distribution':'uniform_discrete','n_samples':n,'n_bits':16,'output_type':'decimal',
             'sample_byte_order':'big-endian, in returned order'}
    elif provider=='nist':
        # Reuse the existing transport/pulse validation, NOT its I Ching bits.
        _,p=nist_beacon.cast(request_id)
        domain=f'gnosis.runes.{mode}.nist-beacon-v2.shake256.v1\x00'.encode('ascii')
        raw=hashlib.shake_256(domain+bytes.fromhex(p['beacon_output_value'])+bytes.fromhex(request_id)).digest(count)
        provenance={k:v for k,v in p.items() if k.startswith('beacon_') or k in ('provider','service','endpoint','signature_verified_locally','public_beacon','independent_entropy_per_consultation','pulse_age_seconds')}
        provenance.update(derivation_version='gnosis-runes-nist-shake256-v1',derivation_domain_hex=domain.hex(),
             derivation_request_id=request_id,derivation='SHAKE256(domain || pulse outputValue bytes || request ID bytes)',
             independent_entropy_per_consultation=False,public_beacon=True)
    else: raise ValueError('Hardware source not qualified')
    if len(raw)!=count: raise ValueError('Incorrect entropy length')
    provenance.update(entropy_bits=count*8,entropy_sha256=hashlib.sha256(raw).hexdigest(),
      cast_utc=datetime.now(timezone.utc).isoformat(),latency_ms=round((time.perf_counter()-started)*1000,2),fallback_used=False,
      qpu_circuit_executed=False, conversion=('MSB-first 5-bit rejection sampling, shrinking pools 24/23/22' if mode=='pouch' else '18 consecutive 64-bit MSB-first words; RC1 decodes low 16-bit fields first'))
    return {'raw_hex':raw.hex(),'provenance':provenance}


def build_reading(service_id,cid,staged):
    mode,source,provider=spec(service_id)
    if provider=='ibm_inventory':
        from .rune_past_inventory import build_past_reading
        return build_past_reading(service_id,cid,staged)
    if provider=='ibm_runtime':
        from .future_execution import build_rune
        return build_rune(service_id,cid,staged)
    raw=bytes.fromhex(staged['raw_hex']); provenance=dict(staged['provenance'])
    if provenance['provider']!=provider or provenance['entropy_sha256']!=hashlib.sha256(raw).hexdigest() or len(raw)!=(24 if mode=='pouch' else 144):
        raise ValueError('Entropy provenance mismatch')
    if mode=='pouch':
        ranks,tried=pouch_ranks(raw); decoded=pouch_payload(ranks)
        decoded['private_audit']['rank_candidates']=tried
        provenance['engine_version']='ordered-rank-decoder-v1'
    else:
        words=[f'{int.from_bytes(raw[i:i+8],"big"):064b}' for i in range(0,144,8)]
        decoded=sticks_payload(words)
        provenance.update(recognition_version=decoded['recognition_version'],profile_sha256=decoded['profile_sha256'])
    reading={'schema_version':SCHEMA,'reading_id':cid,'mode':mode,
             'source':{'server_crypto':'classic','qci':'qci','nist':'nist'}[provider],
             'delivery':'live','status':'ready','provenance':provenance,'payload':decoded['payload']}
    return reading,provenance,{'entropy':staged,'audit':decoded['private_audit']}


def persist_completed(db,row,reading,provenance,private,stamp,schema_version):
    """Invoked only inside the shared settlement transaction. No HTTP or RNG."""
    mode,source,provider=spec(row['service_id']); cid=row['consultation_id']
    stage=db.execute('SELECT status,staged_json FROM rune_executions WHERE request_id=?',(row['request_id'],)).fetchone()
    if not stage or stage['status']!='staged' or schema_version!=SCHEMA or not isinstance(private,dict):
        raise ValueError('Rune settlement requires staged entropy')
    if provider=='ibm_runtime':
        from .future_execution import validate_staged_job
        validate_staged_job(db,row['request_id'],json.loads(stage['staged_json']))
    # Validate canonical payload, including every frame, against the frozen decoder.
    expected,ep,ea=build_reading(row['service_id'],cid,json.loads(stage['staged_json']))
    if packed(expected)!=packed(reading) or packed(ep)!=packed(provenance) or packed(ea)!=packed(private):
        raise ValueError('Rune settlement does not match staged entropy')
    if mode=='pouch': summary={'rune_ids':[d['rune_id'] for d in reading['payload']['draws']]}
    else:
        p=reading['payload']; summary={'shown':sorted(p['timeline']['final']['shown']), 'degenerate_slots':p['casting']['degenerate_slots']}
    if provider=='ibm_inventory':
        from .rune_past_inventory import consume
        consume(db,row,json.loads(stage['staged_json']),stamp)
    encoded=packed(private).encode('utf8')
    db.execute('INSERT INTO rune_private_archives VALUES(?,?,?,?,?)',(cid,mode,gzip.compress(encoded,mtime=0),hashlib.sha256(encoded).hexdigest(),stamp))
    db.execute('INSERT INTO rune_reading_facts VALUES(?,?,?,?,?)',(cid,mode,provider,packed(summary),stamp))
    db.execute("UPDATE rune_executions SET status='completed',staged_json=NULL,updated_at=? WHERE request_id=?",(stamp,row['request_id']))


def run_claimed(db,request):
    from .transactions import finish_request
    rid=request['request_id']; stamp=iso(now())
    if request['status']!='pending': return request['status']
    if request['service_id'].endswith('.quantum_past'):
        from .rune_past_inventory import stage_past
        state=stage_past(db,request)
        if state=='out_of_stock':
            finish_request(db,rid,success=False);return 'failed'
        if state!='staged':return state
    claim=db.execute("INSERT OR IGNORE INTO rune_executions VALUES(?,'claimed',?,NULL,?)",(rid,stamp,stamp)).rowcount==1
    if claim:
        try: staged=acquire(request['service_id'],rid)
        except Exception:
            finish_request(db,rid,success=False)
            return 'failed'
        db.execute("UPDATE rune_executions SET status='staged',staged_json=?,updated_at=? WHERE request_id=? AND status='claimed'",(packed(staged),iso(now()),rid))
    else:
        row=db.execute('SELECT status,staged_json FROM rune_executions WHERE request_id=?',(rid,)).fetchone()
        if row['status']=='claimed': return 'in_progress'
        if row['status'] in ('completed','failed'): return row['status']
        staged=json.loads(row['staged_json'])
    try: reading,provenance,private=build_reading(request['service_id'],request['consultation_id'],staged)
    except ValueError:
        finish_request(db,rid,success=False); return 'failed'
    # DB/worker fault leaves original entropy staged; a retry resumes without a provider call.
    finish_request(db,rid,success=True,result_json=reading,provenance_json=provenance,
                   schema_version=SCHEMA,private_rune_archive=private)
    return 'completed'
