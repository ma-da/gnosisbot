#!/usr/bin/env python3
"""Read-only acceptance checks. No provider requests or DB writes. No raw private output."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,sqlite3,urllib.request,urllib.error,sys,re
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'app/data'
from app.services import corpus as c

def db_snapshot(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row; out={}; db.execute('BEGIN')
    try:
        # Hash the exact values in each row, including original JSON strings and BLOB bytes.
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            quoted='"'+name.replace('"','""')+'"'; h=hashlib.sha256(); rowhashes=[]
            for r in db.execute('SELECT * FROM '+quoted):
                rowhashes.append(c.digest([{'blob_hex':x.hex()} if isinstance(x,bytes) else x for x in r]))
            for dig in sorted(rowhashes):h.update(dig.encode('ascii'))
            out[name]={'rows':len(rowhashes),'sha256':h.hexdigest()}
        return out
    finally:db.close()

def stored_audit(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    rows=c.load(P/'interpretations.json')['hexagrams']; counts={}; failures=[]
    try:
        for r in db.execute("SELECT rr.consultation_id,s.service_id,rr.reading_json,rr.provenance_json FROM reading_results rr JOIN service_requests s ON s.consultation_id=rr.consultation_id WHERE s.service_id LIKE 'iching.%'"):
            try:
                c.project_payload({'service_id':r['service_id'],'reading':json.loads(r['reading_json']),'provenance':json.loads(r['provenance_json'])},rows)
                counts[r['service_id']]=counts.get(r['service_id'],0)+1
            except Exception as exc: failures.append({'consultation_id':r['consultation_id'],'service_id':r['service_id'],'error':type(exc).__name__})
        # Do not serialize or transform original receipt material; validate recorded hashes.
        has=db.execute("SELECT 1 FROM sqlite_master WHERE name='gqtp_receipts'").fetchone(); receipts=0
        if has:
            for r in db.execute('SELECT g.consultation_id,g.opening_json,r.reading_json,r.provenance_json FROM gqtp_receipts g JOIN reading_results r ON r.consultation_id=g.consultation_id'):
                o=json.loads(r['opening_json']);receipts+=1
                if o['reading_sha256']!=c.sha(r['reading_json'].encode()) or o['provenance_sha256']!=c.sha(r['provenance_json'].encode()):failures.append({'consultation_id':r['consultation_id'],'error':'receipt hash mismatch'})
        print(json.dumps({'saved_readings_projected':counts,'receipt_hashes_checked':receipts,'failures':failures},indent=2));return not failures
    finally:db.close()

def live(base):
    def get(path):
        req=urllib.request.Request(base.rstrip('/')+path,headers={'Accept-Encoding':'identity','Cache-Control':'no-cache'})
        try:r=urllib.request.urlopen(req,timeout=20)
        except urllib.error.HTTPError as exc:r=exc
        with r:return r.status,r.headers,r.read(32_000_001)
    expected=c.serialize_catalog(c.load(P/'interpretations.json')['hexagrams']);c.require(c.sha(expected)==c.load(P/'interpretation_manifest.json')['files']['site/hexagrams_catalog.json'],'Local catalog manifest hash mismatch');status,_,b=get('/api/v1/hexagrams');c.require(status==200 and b==expected,'Live catalog is not an exact byte match');print('PASS: live catalog exactly matches reference bytes; 64 records')
    status,_,b=get('/sitemap.xml'); c.require(status==200 and b==(ROOT/'app/data/sitemap.xml').read_bytes(),'Sitemap mismatch'); status,_,b=get('/robots.txt');c.require(status==200 and b'Sitemap: https://gnosis.bot/sitemap.xml' in b,'Robots sitemap missing');print('PASS: sitemap and robots')
    for path in ('/quantum-oracle.html','/rune-oracle.html'):
        status,h,html=get(path);c.require(status==200 and 'noindex' not in h.get('X-Robots-Tag','').lower(),'Public page unavailable or noindex: '+path)
        from html.parser import HTMLParser
        class Meta(HTMLParser):
            noindex=False
            def handle_starttag(self,tag,attrs):
                a=dict(attrs)
                if tag=='meta' and a.get('name','').lower() in ('robots','googlebot') and 'noindex' in a.get('content','').lower():self.noindex=True
        meta=Meta();meta.feed(html.decode('utf-8'));c.require(not meta.noindex,'Landing page has noindex meta: '+path)
        status,h,_=get(path+'?reading=00000000000000000000000000000000');c.require(status==200 and 'noindex' in h.get('X-Robots-Tag','').lower() and 'no-store' in h.get('Cache-Control','').lower(),'Private header missing: '+path)
    print('PASS: public vs private Oracle headers')
    clean_demo=c.load(P/'ibm_demo_128.json'); rows=json.loads(expected)
    status,_,b=get('/api/v1/demo/catalog');c.require(status==200 and not c.LEGACY_MARKER.search(b.decode()),'Demo catalog failed or legacy marker'); catalogue=json.loads(b)['readings']; c.require(len(catalogue)==128,'Unexpected demo catalogue count')
    for i,entry in enumerate(catalogue):
        r=clean_demo['readings'][i]
        want={'index':i,'values':r['line_values_bottom_to_top'],'now':r['now']['king_wen_number'],'becoming':r['becoming']['king_wen_number'],'moving_positions':r['moving_positions_bottom_to_top'],'matches':r['moving_flag_matches']}
        c.require(all(entry.get(k)==v for k,v in want.items()),'Demo clustering input differs at shot '+str(i))
    for i in range(128):
        status,_,b=get('/api/v1/demo/readings/'+str(i));c.require(status==200 and not c.LEGACY_MARKER.search(b.decode()),'Demo reading failed '+str(i)); item=json.loads(b); expected_row=clean_demo['readings'][i]
        c.require(item['reading']==expected_row,'Demo physical or structural row changed '+str(i)); c.require(item['interpretations']=={p:rows[expected_row[p]['king_wen_number']-1] for p in ('now','becoming')},'Wrong literature join '+str(i))
    print('PASS: all 128 live demo readings match cleaned physical records and new catalog')
    status,h,_=get('/api/v1/accounts/readings/00000000000000000000000000000000');c.require(status in (401,403,404) and 'noindex' in h.get('X-Robots-Tag','').lower(),'Unauthenticated reading boundary failed');print('PASS: unauthenticated replay denied')

def static_audit():
    # Report file paths, not matching text. Includes staged adapters and source comments for review.
    findings=[]
    for p in sorted((ROOT/'app/static').rglob('*')):
        if p.is_file() and p.suffix.lower() in ('.html','.js','.json','.txt','.xml','.css','.md','.svg'):
            try: s=p.read_text(encoding='utf-8')
            except UnicodeError:continue
            if c.LEGACY_MARKER.search(s):findings.append(str(p.relative_to(ROOT)))
    print(json.dumps({'static_files_with_legacy_markers_review_required':findings},indent=2));return not findings

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--compare',type=Path);p.add_argument('--stored',action='store_true');p.add_argument('--live');p.add_argument('--static',action='store_true');a=p.parse_args();ok=True
    if a.snapshot or a.compare or a.stored:c.require(a.db is not None,'--db required')
    if a.snapshot:
        with a.snapshot.open('x') as f:json.dump(db_snapshot(a.db),f,indent=2)
        print('Snapshot saved (hashes and counts only)')
    if a.compare:c.require(db_snapshot(a.db)==json.loads(a.compare.read_text()),'Database differs from pre-migration snapshot');print('PASS: all database tables unchanged')
    if a.stored:ok=stored_audit(a.db) and ok
    if a.live:live(a.live)
    if a.static:ok=static_audit() and ok
    if not ok:sys.exit(1)
if __name__=='__main__':main()
