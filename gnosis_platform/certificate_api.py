"""Owner-only endpoints; no publicly addressable certificate or token."""
import json,re,secrets,html
from contextlib import closing
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import JSONResponse,Response,HTMLResponse
from .auth_api import authenticated,guard_origin
from .config import get_settings
from .db import connect
from .certificate_store import SCHEMA,LEGACY_SCHEMA,verify_record,key_paths,stamp
from . import gqtp as g
from .certificate_validation import sha

router=APIRouter(tags=['gnosis-certificates'])
HEADERS={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}
def validate_row(db,row):
    data=get_settings().data_dir
    try:
        cid=row['consultation_id']
        saved=db.execute('SELECT reading_json,provenance_json FROM reading_results WHERE consultation_id=?',(cid,)).fetchone()
        receipt=g.receipt(db,cid,n=row['checkpoint_size'])
        pinned=(data/'transparency/public/public-key.txt').read_text().strip()
        valid=verify_record(row,data) and saved is not None and sha(saved[0].encode())==row['reading_sha256'] and sha(saved[1].encode())==row['provenance_sha256'] and g.verify_receipt(receipt,pinned) and receipt['event']['seq']==row['gqtp_seq']
    except Exception:valid=False
    if not valid:raise HTTPException(503,'Certificate verification requires operator review',headers=HEADERS)
    return row

def owner_record(cid,user,certificate_id=None):
    if not re.fullmatch('[0-9a-f]{32}',cid):raise HTTPException(404,'Certificate not found',headers=HEADERS)
    with closing(connect()) as db:
        row=db.execute("""SELECT x.* FROM reading_certificates x JOIN consultations c USING(consultation_id) WHERE x.consultation_id=? AND c.account_id=? AND c.status='completed' AND x.schema_version IN (?,?) AND (? IS NULL OR x.certificate_id=?) ORDER BY x.schema_version DESC LIMIT 1""",(cid,user['account_id'],SCHEMA,LEGACY_SCHEMA,certificate_id,certificate_id)).fetchone()
        if row is None:raise HTTPException(404,'Certificate not found',headers=HEADERS)
        return validate_row(db,row)
@router.get('/accounts/readings/{consultation_id}/certificate')
def certificate(consultation_id:str,user:dict=Depends(authenticated)):
    row=owner_record(consultation_id,user)
    return JSONResponse({'status':'ready','certificate_id':row['certificate_id'],'kind':row['kind'],'issued_at':row['issued_at'],'verify_status':'valid','image_url':f'/api/v1/accounts/readings/{consultation_id}/certificate.png'},headers=HEADERS)
@router.get('/accounts/readings/{consultation_id}/certificate.png')
def png(consultation_id:str,user:dict=Depends(authenticated),download:bool=False,certificate_id:str|None=None):
    row=owner_record(consultation_id,user,certificate_id)
    disposition='attachment' if download else 'inline'
    return Response(row['asset_png'],media_type='image/png',headers={**HEADERS,'Content-Disposition':f'{disposition}; filename="gnosis-{row["certificate_id"]}.png"'})
@router.get('/accounts/readings/{consultation_id}/certificate/metadata')
def metadata(consultation_id:str,user:dict=Depends(authenticated),certificate_id:str|None=None):
    row=owner_record(consultation_id,user,certificate_id);_,pub=key_paths(get_settings().data_dir)
    return JSONResponse({'payload':json.loads(row['payload_json']),'payload_sha256':row['payload_sha256'],'asset_sha256':row['asset_sha256'],'signature_hex':row['signature_hex'],'key_id':row['key_id'],'public_key_hex':pub.read_text().strip(),'signature_scheme':'Ed25519 over GNOSIS-CERTIFICATE-V1 NUL + binary payload SHA-256 + binary PNG SHA-256','issued_at':row['issued_at'],'verification_url':f'/api/v1/accounts/readings/{consultation_id}/verification'},headers=HEADERS)

# Share links are explicit, unguessable, revocable bearer URLs. No raw token is persisted.
# Creating a link again intentionally rotates it; no secret is recovered from the DB.
PUBLIC_HEADERS={**HEADERS,'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow, noarchive','Content-Security-Policy':"default-src 'none'; img-src 'self'; style-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}
@router.post('/accounts/readings/{consultation_id}/certificate/share',dependencies=[Depends(guard_origin)])
def share(consultation_id:str,user:dict=Depends(authenticated),certificate_id:str|None=None):
    row=owner_record(consultation_id,user)
    if certificate_id is not None and certificate_id!=row['certificate_id']:
        raise HTTPException(409,'Certificate revision changed; refresh account',headers=HEADERS)
    token=secrets.token_urlsafe(32)
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            # Revoke prior revision links for this reading when explicitly replacing a link.
            db.execute('UPDATE certificate_shares SET revoked_at=? WHERE certificate_id IN (SELECT certificate_id FROM reading_certificates WHERE consultation_id=?) AND revoked_at IS NULL',(stamp(),consultation_id))
            db.execute('INSERT INTO certificate_shares VALUES(?,?,?,NULL) ON CONFLICT(certificate_id) DO UPDATE SET token_hash=excluded.token_hash,enabled_at=excluded.enabled_at,revoked_at=NULL',(row['certificate_id'],sha(token.encode('ascii')),stamp()))
            db.commit()
        except Exception:db.rollback();raise
    return JSONResponse({'share_path':'/api/v1/c/'+token,'certificate_id':row['certificate_id']},headers=HEADERS)

@router.delete('/accounts/readings/{consultation_id}/certificate/share',dependencies=[Depends(guard_origin)])
def revoke_share(consultation_id:str,user:dict=Depends(authenticated)):
    # Revocation remains possible even when a certificate fails verification.
    with closing(connect()) as db:
        db.execute('UPDATE certificate_shares SET revoked_at=? WHERE certificate_id IN (SELECT x.certificate_id FROM reading_certificates x JOIN consultations c USING(consultation_id) WHERE x.consultation_id=? AND c.account_id=?) AND revoked_at IS NULL',(stamp(),consultation_id,user['account_id']))
    return JSONResponse({'revoked':True},headers=HEADERS)

def public_record(token):
    if not re.fullmatch('[A-Za-z0-9_-]{43}',token):raise HTTPException(404,'Share not found',headers=PUBLIC_HEADERS)
    with closing(connect()) as db:
        row=db.execute('SELECT x.* FROM reading_certificates x JOIN certificate_shares s USING(certificate_id) WHERE s.token_hash=? AND s.revoked_at IS NULL',(sha(token.encode('ascii')),)).fetchone()
        if row is None:raise HTTPException(404,'Share not found',headers=PUBLIC_HEADERS)
        try:return validate_row(db,row)
        except HTTPException:raise HTTPException(503,'Certificate verification requires operator review',headers=PUBLIC_HEADERS)

@router.get('/c/{token}')
def shared_page(token:str):
    row=public_record(token);p=json.loads(row['payload_json']);title='Certificate of Quantum Authenticity' if row['kind']=='quantum_hardware' else 'Gnosis Reading Certificate'
    safe=html.escape
    body=f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{safe(title)} | Gnosis.bot</title><h1>{safe(title)}</h1><p>{safe(p['method_label'])}</p><p>Gnosis signature and saved-reading GQTP receipt verified by the server. This is not an IBM-issued certificate or prediction guarantee.</p><p><a href="{token}/image.png">View or save signed PNG</a> · <a href="{token}/verification">Signature and image digest</a></p><img src="{token}/image.png" width="600" alt="Shared Gnosis reading certificate"><p><a href="/api/v1/transparency/checkpoints/{row['checkpoint_size']}">Signed GQTP checkpoint</a></p></html>"""
    return HTMLResponse(body,headers=PUBLIC_HEADERS)
@router.get('/c/{token}/image.png')
def shared_png(token:str):
    row=public_record(token)
    return Response(row['asset_png'],media_type='image/png',headers=PUBLIC_HEADERS)
@router.get('/c/{token}/verification')
def shared_verification(token:str):
    row=public_record(token);_,pub=key_paths(get_settings().data_dir)
    return JSONResponse({'status':'valid','certificate_id':row['certificate_id'],'payload_sha256':row['payload_sha256'],'asset_sha256':row['asset_sha256'],'signature_hex':row['signature_hex'],'public_key_hex':pub.read_text().strip(),'key_id':row['key_id'],'signature_scheme':'Ed25519 over GNOSIS-CERTIFICATE-V1 NUL + binary payload SHA-256 + binary PNG SHA-256','checkpoint_size':row['checkpoint_size'],'note':'Public signature binds the displayed PNG and payload digest; private payload and receipt are not exposed. GQTP receipt verified server-side.'},headers=PUBLIC_HEADERS)
