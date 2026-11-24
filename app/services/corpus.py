"""I Ching v0.9 presentation boundary. Never writes a database or casts entropy."""
from __future__ import annotations
import json, re, hashlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs
from starlette.responses import JSONResponse, Response, FileResponse

DATA = Path(__file__).resolve().parents[1] / 'data'
OLD_KEYS = frozenset('poem_title richter_heading richter_heading_in_book brief_interpretation reflection_question source_pdf_page_richter source_pdf_page_poem source_attribution book_source_url interpretation_source_id poems_by translation_by art_by book_page license_notice credit_line website_rights_notice usage_note original_richter_translation_note metadata_required_in_app rights_and_usage_note display_credit historical_text_basis poetic_title_basis translation_book_pdf_page sonnet_book_pdf_page'.split())
LITERARY = OLD_KEYS | frozenset('interpretations interpretation literary_provenance classical taoist confucian historical_core modern_meaning archetypal_meaning essence advice shadow themes'.split())
LEGACY_MARKER = re.compile(r'(?i)(mitteldorf|\brichter\b|meryl ann butler|i-chingguru\.vercel\.app|i ching sonnets|richter_heading|source_pdf_page_)')
HEXAGRAM_BITS = '111111 000000 100010 010001 111010 010111 010000 000010 111011 110111 111000 000111 101111 111101 001000 000100 100110 011001 110000 000011 100101 101001 000001 100000 100111 111001 100001 011110 010010 101101 001110 011100 001111 111100 000101 101000 101011 110101 001010 010100 110001 100011 111110 011111 000110 011000 010110 011010 101110 011101 100100 001001 001011 110100 101100 001101 011011 110110 010011 110010 110011 001100 101010 010101'.split()

def require(condition, message):
    if not condition: raise ValueError(message)

def sha(data): return hashlib.sha256(data).hexdigest()
def digest(value): return sha(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def load(path): return json.loads(Path(path).read_bytes())

def validate_corpus(data, ref=None):
    require(data['schema_version']=='2.0.0' and isinstance(data['corpus_version'],str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',data['corpus_version']),'Wrong release')
    require(data['records_total']==192 and isinstance(data['status'],str) and bool(data['status'].strip()),'Unexpected editorial status')
    rows=data['hexagrams']; require(len(rows)==64,'Expected 64 records')
    require(ref is None or rows==ref,'Catalog and corpus differ')
    for i,r in enumerate(rows,1):
        require(r['number']==r['king_wen_number']==i and r['bits']==r['line_bits_bottom_to_top']==HEXAGRAM_BITS[i-1] and r['symbol']==chr(0x4dc0+i-1),f'Identity mismatch {i}')
        require(r['corpus_version']==data['corpus_version'] and r['editorial_status']==data['status'],f'Metadata mismatch {i}')
        require(set(r['human_approved'])=={'classical','taoist','confucian'} and all(type(v) is bool for v in r['human_approved'].values()),f'Approval mismatch {i}')
        require(set(r['record_hashes'])=={'classical','taoist','confucian'} and all(re.fullmatch('[0-9a-f]{64}',h) for h in r['record_hashes'].values()),f'Record hash malformed {i}')
        for t in ('classical','taoist','confucian'):
            obj=r[t]; require([l['position'] for l in obj['lines']]==list(range(1,7)),f'Line order {i}/{t}')
            keys=('judgment_zh','judgment_en','image_zh','image_en','historical_note') if t=='classical' else ('title','essence','archetypal_meaning','historical_core','modern_meaning','advice','shadow','reflection_question')
            require(all(isinstance(obj[k],str) and obj[k].strip() for k in keys),f'Empty text {i}/{t}')
            linekeys=('label_zh','text_zh','translation_en') if t=='classical' else ('interpretation','reflection','evidence_zh')
            require(all(all(isinstance(l[k],str) and l[k].strip() for k in linekeys) for l in obj['lines']),f'Empty line {i}/{t}')
            require(bool(obj.get('special'))==(i in (1,2)),f'Special passage {i}/{t}')
    require(data['human_approved_records']==sum(sum(r['human_approved'].values()) for r in rows),'Aggregate approval mismatch')
    require(not LEGACY_MARKER.search(json.dumps(data,ensure_ascii=False)), 'Obsolete marker in corpus')
    return rows

@lru_cache(maxsize=8)
def _corpus_cached(signature):
    data=load(DATA/'interpretations.json'); validate_corpus(data); return data


def _corpus_signature():
    st=(DATA/'interpretations.json').stat()
    return (st.st_ino,st.st_size,st.st_mtime_ns)


def corpus():
    return _corpus_cached(_corpus_signature())


corpus.cache_clear=_corpus_cached.cache_clear


def serialize_catalog(rows):
    return (json.dumps(rows,ensure_ascii=False,indent=2)+'\n').replace('\n','\r\n').encode('utf-8')

@lru_cache(maxsize=8)
def _catalog_cached(signature):
    return serialize_catalog(corpus()['hexagrams'])


def catalog_bytes():
    return _catalog_cached(_corpus_signature())


catalog_bytes.cache_clear=_catalog_cached.cache_clear

def physical_projection(d):
    # Same canonical projection as original migration toolkit.
    import copy
    d=copy.deepcopy(d); d.pop('source_attribution',None); d.pop('experiment',None); d['circuit_metadata'].pop('book_source_url',None)
    for r in d['readings']:
        for t in ('now','becoming'):
            r[t]={k:r[t][k] for k in ('king_wen_number','hexagram_symbol','line_bits_bottom_to_top')}
    return d

def clean(value):
    if isinstance(value,list): return [clean(v) for v in value]
    if not isinstance(value,dict): return value
    # Do not touch unrelated customer prose, physical timestamps, hashes or measurements.
    return {k:clean(v) for k,v in value.items() if k not in LITERARY and not k.startswith('source_pdf_page_') and not (k=='sources' and LEGACY_MARKER.search(json.dumps(v,ensure_ascii=False)))}

def bits_string(v):
    if isinstance(v,list): v=''.join(str(x) for x in v)
    require(isinstance(v,str) and re.fullmatch('[01]{6}',v),'Invalid hexagram pattern')
    return v

def phase_record(reading,phase,rows):
    old=reading.get(phase,{})
    require(isinstance(old,dict),'Invalid phase record')
    b=[bits_string(v) for v in (reading.get(phase+'_bits_bottom_to_top'),reading.get(phase+'_yang_bits_bottom_to_top'),old.get('line_bits_bottom_to_top'),old.get('bits')) if v is not None]
    require(bool(b) and len(set(b))==1,'Missing or conflicting bit pattern')
    record=rows[HEXAGRAM_BITS.index(b[0])]
    for k in ('number','king_wen_number'):
        if k in old: require(type(old[k]) is int and old[k]==record['number'],'King Wen mismatch')
    for k in ('symbol','hexagram_symbol'):
        if k in old: require(old[k]==record['symbol'],'Symbol mismatch')
    return record

def project_reading(reading,rows):
    require(isinstance(reading,dict),'Invalid reading')
    refs={p:phase_record(reading,p,rows) for p in ('now','becoming')}
    # Validate, never recalculate or modify, the physical and classical line fields.
    vals=reading.get('line_values_bottom_to_top',reading.get('lines'))
    if isinstance(vals,list) and vals and isinstance(vals[0],dict): vals=[l['value'] for l in vals]
    require(isinstance(vals,list) and len(vals)==6 and all(type(v) is int and v in (6,7,8,9) for v in vals),'Invalid line values')
    n=''.join(str(v%2) for v in vals); b=''.join(str(v%2 ^ int(v in (6,9))) for v in vals)
    require(n==refs['now']['bits'] and b==refs['becoming']['bits'],'Line/pattern mismatch')
    require(reading.get('moving_positions_bottom_to_top')==[i+1 for i,v in enumerate(vals) if v in (6,9)],'Moving position mismatch')
    result=clean(reading)
    for p in refs:
        if p in reading:
            # Older phase objects include literary fields but may carry additional physical keys.
            phase=clean(reading[p]); phase.pop('title',None); phase.pop('name',None); phase.pop('sources',None)
            result[p]=phase
    return result,refs

def project_payload(value,rows,*,demo=False):
    # Service-neutral endpoint can include rune envelopes: leave them completely untouched.
    if not isinstance(value,dict): return value
    service=value.get('service_id') or (value.get('receipt') or {}).get('service_id')
    if (isinstance(service,str) and not service.startswith('iching.')) or value.get('application_id')=='runes': return value
    out=dict(value)
    if isinstance(value.get('reading'),dict):
        reading=value['reading']
        if reading.get('application_id')=='runes' or reading.get('schema_version','').startswith('gnosis.rune') or 'payload' in reading: return value
        out['reading'],out['interpretations']=project_reading(reading,rows)
        if 'provenance' in value: out['provenance']=clean(value['provenance'])
        out['literary_provenance']={'corpus_version':rows[0]['corpus_version'],'schema_version':'2.0.0','editorial_status':rows[0]['editorial_status'],'catalog_url':'/api/v1/hexagrams','presentation_only':True}
    if isinstance(value.get('result'),dict): out['result']=project_payload(value['result'],rows,demo=demo)
    if demo and not isinstance(value.get('reading'),dict):
        out=clean(out)
        if isinstance(out.get('experiment'),str) and LEGACY_MARKER.search(out['experiment']):out.pop('experiment')
    if demo and isinstance(value.get('readings'),list):
        # Catalog rows may be lightweight cluster entries: retain their fields and order.
        out['readings']=[clean(r) for r in value['readings']]
        for r in out['readings']:
            if isinstance(r,dict):
                for p in ('now','becoming'):
                    if isinstance(r.get(p),dict):
                        r[p].pop('title',None);r[p].pop('name',None);r[p].pop('sources',None)
        for key in ('source_attribution','interpretations','display_credit'):out.pop(key,None)
        if 'provenance' in out:out['provenance']=clean(out['provenance'])
    if isinstance(out.get('reading'),dict) or demo:
        for key in ('reading','provenance','readings','experiment','source_attribution'):
            require(not LEGACY_MARKER.search(json.dumps(out.get(key),ensure_ascii=False)), 'Unrecognized legacy attribution in '+key)
    return out

def private_path(path,query):
    private_pages={'/account','/account.html','/reading-history','/reading-history.html','/qci-reading.html','/ibm-trial-pending.html'}
    oracle_pages={'/quantum-oracle','/quantum-oracle.html','/rune-oracle','/rune-oracle.html'}
    # Also cover static asset alias, trailing slash and any URL with a reading parameter.
    p=path.rstrip('/') or '/'; p=p.removeprefix('/assets') if p.startswith('/assets/') else p
    return (p in private_pages or p.startswith(('/admin/','/api/v1/accounts/','/api/v1/consultations/','/api/v1/ibm-future/')) or p in ('/admin','/api/v1/accounts','/api/v1/consultations') or (p in oracle_pages and 'reading' in parse_qs(query,keep_blank_values=True)))

class CorpusPresentation:
    """Scoped ASGI projection after auth/settlement. Receipts and nonreading APIs pass byte-exact."""
    def __init__(self, app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        path=scope['path']; method=scope['method']; private=private_path(path,scope.get('query_string',b'').decode('latin1'))
        # Serve the authoritative array directly; avoids legacy response-model filtering.
        if method in ('GET','HEAD') and path=='/api/v1/hexagrams':
            body=catalog_bytes()
            response=Response(body if method=='GET' else b'',media_type='application/json',headers={'Cache-Control':'no-cache','Content-Length':str(len(body))})
            return await response(scope,receive,send)
        if method in ('GET','HEAD') and path in ('/sitemap.xml','/robots.txt'):
            name=path[1:]; return await FileResponse(DATA/name,media_type='application/xml' if name.endswith('.xml') else 'text/plain',headers={'Cache-Control':'no-cache'})(scope,receive,send)
        demo=path.startswith('/api/v1/demo/')
        project=demo or (path=='/api/v1/consultations' and method=='POST') or bool(re.fullmatch(r'/api/v1/(?:consultations|accounts/readings)/[^/]+',path))
        def headers(msg):
            h=list(msg.get('headers',[]))
            if private:
                h=[(k,v) for k,v in h if k.lower() not in (b'x-robots-tag',b'cache-control')]+[(b'x-robots-tag',b'noindex, nofollow'),(b'cache-control',b'private, no-store')]
            return h
        start=None; chunks=[]; size=0
        async def filtered(msg):
            nonlocal start,size
            if msg['type']=='http.response.start':
                msg=dict(msg,headers=headers(msg)); hd=dict(msg['headers']); status=msg['status']
                if project and method!='HEAD' and 200<=status<300 and b'application/json' in hd.get(b'content-type',b''):
                    start=msg; return
                return await send(msg)
            if start is None:return await send(msg)
            if msg['type']!='http.response.body':return
            chunk=msg.get('body',b'');size+=len(chunk)
            if size<=32_000_000: chunks.append(chunk)
            if msg.get('more_body'):return
            try:
                require(size<=32_000_000,'Response too large')
                import gzip
                raw=b''.join(chunks); enc=dict(start['headers']).get(b'content-encoding',b'identity')
                if enc==b'gzip':raw=gzip.decompress(raw)
                else:require(enc==b'identity','Unsupported response encoding')
                obj=json.loads(raw); revised=project_payload(obj,corpus()['hexagrams'],demo=demo)
                if revised==obj:
                    await send(start); await send({'type':'http.response.body','body':b''.join(chunks)});return
                body=json.dumps(revised,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
                h=[(k,v) for k,v in start['headers'] if k.lower() not in (b'content-length',b'etag',b'content-encoding',b'content-md5',b'digest')]
                await send(dict(start,headers=h+[(b'content-length',str(len(body)).encode())]));await send({'type':'http.response.body','body':body})
            except (ValueError,KeyError,TypeError,IndexError, OSError):
                # A completed consultation stays completed. Client must retrieve same ID; never reroll.
                await JSONResponse({'detail':'Reading presentation unavailable; retrieve the existing consultation without recasting.'},status_code=500,headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex'})(scope,receive,send)
        await self.app(scope,receive,filtered)
