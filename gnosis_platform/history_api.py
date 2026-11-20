"""Authenticated complete-reading history. No public question-level endpoint."""
import json
from fastapi import Response as _RuneResponse
from contextlib import closing
from fastapi import APIRouter, Depends, HTTPException
from .auth_api import authenticated
from .db import connect

router=APIRouter(prefix='/api/v1',tags=['gnosis-reading-history'])

@router.get('/accounts/readings')
def account_readings(user:dict=Depends(authenticated),limit:int=25,offset:int=0,
                     source:str|None=None):
    if not 1<=limit<=100 or not 0<=offset<=100000:
        raise HTTPException(422,'Invalid pagination')
    if source is not None and (not source or len(source)>80):
        raise HTTPException(422,'Invalid source')
    # Joined to source via service request, not research projections, so the
    # history works for prior readings even if backfill has not run yet.
    where="c.account_id=? AND c.status='completed'"
    args=[user['account_id']]
    if source:
        where+=' AND sr.provider=?'
        args.append(source)
    with closing(connect()) as db:
        total=db.execute(f'''SELECT COUNT(*) FROM consultations c
            JOIN reading_results r ON r.consultation_id=c.consultation_id
            JOIN service_requests sr ON sr.consultation_id=c.consultation_id
            WHERE {where}''',args).fetchone()[0]
        rows=db.execute(f'''SELECT c.consultation_id,c.application_id,c.question,c.inquiry_style,c.created_at,c.finished_at,
            sr.service_id,sr.provider,r.reading_json
            FROM consultations c JOIN reading_results r ON r.consultation_id=c.consultation_id
            JOIN service_requests sr ON sr.consultation_id=c.consultation_id
            WHERE {where} ORDER BY c.finished_at DESC,c.consultation_id DESC LIMIT ? OFFSET ?''',
            [*args,limit,offset]).fetchall()
        items=[]
        for row in rows:
            item=dict(row)
            reading=json.loads(item.pop('reading_json'))
            if item['application_id']=='runes':
                item['mode']=reading['mode']
                item['open_url']='/rune-oracle.html?reading='+item['consultation_id']
            else:
                item['moving_count']=len(reading.get('moving_positions_bottom_to_top',[]))
                item['lines']=reading.get('lines',[])
            items.append(item)
    return {'items':items,'total':total,'limit':limit,'offset':offset}

@router.get('/accounts/readings/{consultation_id}')
def account_reading(consultation_id:str,user:dict=Depends(authenticated),response: _RuneResponse=None):
    if response is not None: response.headers['Cache-Control']='no-store'
    if len(consultation_id)!=32 or any(ch not in '0123456789abcdef' for ch in consultation_id):
        raise HTTPException(404,'Reading not found')
    with closing(connect()) as db:
        row=db.execute('''SELECT c.consultation_id,c.application_id,c.question,c.inquiry_style,c.created_at,c.finished_at,
          sr.service_id,sr.provider,r.schema_version,r.reading_json,r.provenance_json
          FROM consultations c JOIN reading_results r ON r.consultation_id=c.consultation_id
          JOIN service_requests sr ON sr.consultation_id=c.consultation_id
          WHERE c.consultation_id=? AND c.account_id=? AND c.status='completed' ''',
          (consultation_id,user['account_id'])).fetchone()
        if not row: raise HTTPException(404,'Reading not found')
        result=dict(row)
        result['reading']=json.loads(result.pop('reading_json'))
        result['provenance']=json.loads(result.pop('provenance_json'))
    return result

from . import gqtp_api as _gqtp_api
router.include_router(_gqtp_api.router)
