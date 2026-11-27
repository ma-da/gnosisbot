"""Render only frozen, signed certificate content; never question or raw shots."""
from html import escape
from urllib.parse import urlsplit,urlencode
import json
from .certificate_store import verify_record
from .certificate_validation import need,sha

def certified_record(db,rid,data):
    row=db.execute('''SELECT x.*,e.consultation_id AS event_cid,r.reading_json,r.provenance_json FROM reading_completion_events e
      JOIN reading_certificates x ON x.certificate_id=e.certificate_id AND x.consultation_id=e.consultation_id
      JOIN reading_results r ON r.consultation_id=e.consultation_id
      WHERE e.request_id=? AND e.state='ready' AND e.notify_requested=1''',(rid,)).fetchone()
    need(row is not None and verify_record(row,data),'certificate_missing_or_invalid')
    need(sha(row['reading_json'].encode())==row['reading_sha256'] and sha(row['provenance_json'].encode())==row['provenance_sha256'],'certificate_source_changed')
    from . import gqtp as g
    pinned=(data/'transparency/public/public-key.txt').read_text().strip()
    receipt=g.receipt(db,row['event_cid'],n=row['checkpoint_size'])
    need(g.verify_receipt(receipt,pinned) and receipt['event']['seq']==row['gqtp_seq'],'certificate_receipt_invalid')
    return row

def prepared_message(row,*,recipient,sender,base_url):
    u=urlsplit(base_url);need(u.scheme=='https' and bool(u.hostname) and not u.username and not u.password and u.path in ('','/') and not u.query and not u.fragment,'invalid_public_base')
    for value in (recipient,sender):need('@' in value and not any(c in value for c in '\r\n'),'invalid_email')
    p=json.loads(row['payload_json']);r=p['reading'];s=p['source'];service=p['service_id']
    mode='coins' if service.startswith('iching.') else service.split('.')[1]
    name={'coins':'I Ching','pouch':'Rune Pouch','sticks':'Circular Sticks'}[mode]
    # Both links land on the account login/history view; never a public share token.
    base=base_url.rstrip('/')+'/account.html?'+urlencode({'view':'activity','mode':mode,'reading':row['consultation_id']})
    cert_url=base+'&certificate=1'
    entries=[]
    if mode=='coins':
        for key,label in [('now','Now'),('becoming','Becoming')]:
            x=r[key];entries.append((f'{label} · Hexagram {x["number"]:02d} · {x["title"]}',x['one_liner']))
        entries.append(('Changing lines',', '.join(map(str,r['moving_positions'])) or 'None'))
    elif mode=='pouch':
        for x in r['draws']:entries.append((f'{x["position"].title()} · {x["glyph"]} {x["name"]}',x['one_liner']))
    else:
        for x in r['recognized']:entries.append((f'{x["glyph"]} {x["name"]}',x['one_liner']))
        if not entries:entries.append(('Circular Sticks','No qualifying rune formation recognized'))
        for compound in r.get('compounds',[]):entries.append(('Recognized compound',' + '.join(compound)))
    facts=[('Source',s['label']),('Completed (UTC)',p['reading_completed_at'])]
    for k,label in [('logical_qubits','Logical qubits'),('backend','Backend'),('ibm_job_id','IBM job'),('batch_id','Batch'),('measured_shots','Measured shots'),('shots_per_casting','Hardware shots per casting'),('circuit_version','Circuit')]:
        if k in s:facts.append((label,str(s[k])))
    facts.append(('GQTP signed checkpoint',str(p['integrity']['checkpoint_size'])))
    title='Your Gnosis '+name+' reading is ready';notice='Your question is not included. Sign in with the same Gnosis account to open the reading or certificate. A Gnosis certificate documents recorded provenance; it is not an IBM-issued certificate or prediction guarantee.'
    plain='\n\n'.join([title,p['method_label'],*[a+'\n'+b for a,b in entries],*[a+': '+b for a,b in facts],'Open reading: '+base,'View certificate: '+cert_url,notice])
    esc=lambda x:escape(str(x),quote=True)
    cards=''.join('<div style="border-top:1px solid #c5b17a;padding:14px 0"><strong style="color:#146c68">'+esc(a)+'</strong><p style="margin:6px 0">'+esc(b)+'</p></div>' for a,b in entries)
    details=''.join('<div><strong>'+esc(a)+':</strong> '+esc(b)+'</div>' for a,b in facts)
    html='<!doctype html><html lang="en"><body style="margin:0;background:#f8f7f2;color:#202527;font-family:Arial,sans-serif"><div style="max-width:600px;margin:auto;padding:24px"><div style="font-weight:bold;color:#146c68;font-size:22px;border-bottom:2px solid #b99236;padding-bottom:12px">GNOSIS.BOT</div><h1 style="font-size:26px">'+esc(title)+'</h1><p style="color:#146c68">'+esc(p['method_label'])+'</p>'+cards+'<h2 style="font-size:18px;color:#146c68">Source &amp; verification</h2><div style="font-size:14px;line-height:1.6;overflow-wrap:anywhere">'+details+'</div><p style="margin-top:24px"><a style="color:#146c68;font-weight:bold" href="'+esc(base)+'">Open reading</a> &nbsp;|&nbsp; <a style="color:#146c68;font-weight:bold" href="'+esc(cert_url)+'">View certificate</a></p><p style="font-size:13px;color:#526064">'+esc(notice)+'</p></div></body></html>'
    return {'from':sender,'to':[recipient],'subject':title,'text':plain,'html':html}
