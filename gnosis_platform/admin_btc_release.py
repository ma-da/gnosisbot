"""Release only already-qualified, signed inventory after successful BTC verification.
Called inside the same database transaction as the administrative verification record.
No external I/O here. No provider submission, allocations, or charging.
"""
import json
from . import gqtp as g


def release_verified(db, n, checkpoint_bytes, proof_sha256, method, evidence):
    g.require(db.in_transaction, 'Verification record and stock release must be atomic')
    g.require(g.enforced(db), 'Inventory enforcement not established')
    env=json.loads(checkpoint_bytes)
    c=env['checkpoint']
    g.require(c['tree_size']==n, 'Checkpoint size mismatch')
    prior=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(n,)).fetchone()
    g.require(prior and prior[0].encode('ascii')==checkpoint_bytes,'Checkpoint changed during check')
    events=g.events(db,n)
    g.require(g.root([g.leaf(g.canonical(e)) for e in events]).hex()==c['root'],'Signed ledger prefix mismatch')
    results=[]
    for b in db.execute('SELECT * FROM gqtp_batches ORDER BY seq').fetchall():
        if b['seq']>n:continue
        bt,it=g.batch_tables(b['engine']); job=b['job_id']; bid=b['batch_id']
        live=db.execute(f'SELECT * FROM {bt} WHERE batch_id=?',(bid,)).fetchone()
        g.require(live is not None,'Missing registered batch')
        # Never resurrect withdrawn stock or change previously approved stock.
        if live['status']!='quarantined':continue
        items=db.execute('SELECT * FROM gqtp_items WHERE job_id=? ORDER BY seq',(job,)).fetchall()
        g.require(items,'Missing inventory commitments')
        if items[-1]['seq']>n:continue
        q=db.execute('SELECT metadata_json FROM gqtp_qualifications WHERE batch_id=?',(bid,)).fetchone()
        g.require(q,'Missing qualification')
        qm=json.loads(q[0]); event=events[b['seq']-1]
        archive=live['source_file_sha256'] if b['engine']=='iching' else live['archive_sha256']
        g.require(qm.get('remote_measurements_match') is True and qm.get('mode')==b['engine'] and qm.get('external_job_id')==job==live['external_job_id'] and qm.get('circuit_sha256')==live['circuit_sha256']==event.get('circuit_sha256') and qm.get('archive_sha256')==archive==event.get('archive_sha256') and event.get('kind')=='batch_committed' and event.get('ibm_job_id')==job and event.get('engine')==b['engine'],'Qualification or committed provenance mismatch')
        if b['engine']!='iching':g.require(live['mode']==b['engine'],'Wrong rune mode')
        stock={r['item_id']:r for r in db.execute(f'SELECT item_id,sample_index,state,consultation_id FROM {it} WHERE batch_id=?',(bid,))}
        g.require(len(stock)==len(items)==live['item_count']==event['count'],'Inventory count mismatch')
        commercial=0
        for i in items:
            s=stock.get(i['item_id']); ie=events[i['seq']-1]
            g.require(s and s['sample_index']==i['sample_index'] and s['consultation_id'] is None and ie['kind']=='inventory_committed' and ie['measurement_id']==i['measurement_id'] and ie['disposition']==i['disposition'],'Inventory identity mismatch')
            g.require(s['state']==('available' if i['disposition']=='commercial' else 'void'),'Unexpected stock state')
            commercial+=int(i['disposition']=='commercial')
        g.require(commercial==event['commercial_count'] and commercial>0,'Commercial count mismatch')
        if b['release_checkpoint'] is None:
            note={'method':method,'proof_sha256':proof_sha256,'operator':'admin_btc_auto_release','verified_at':g.stamp(),'evidence':evidence}
            db.execute('UPDATE gqtp_batches SET release_checkpoint=?,verification_note=? WHERE job_id=?',(n,g.canonical(note).decode('ascii'),job))
            g.append(db,'batch_released',{'ibm_job_id':job,'checkpoint_size':n,'ots_proof_sha256':proof_sha256,'verification_method':method})
        else:
            # A previously verified but not approved batch may be approved after a fresh valid proof.
            g.require(b['release_checkpoint']<=n,'Previously released checkpoint not covered')
        changed=db.execute(f"UPDATE {bt} SET status='approved',approved_at=?,approved_by=? WHERE batch_id=? AND status='quarantined'",(g.stamp(),'admin_btc_auto_release',bid)).rowcount
        g.require(changed==1,'Inventory release race')
        results.append({'engine':b['engine'],'ibm_job_id':job,'commercial_count':commercial})
    return results
