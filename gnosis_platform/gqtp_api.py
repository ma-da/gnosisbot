"""Read-only public signed log, and owner-only verification receipts."""
import json
from contextlib import closing
from fastapi import APIRouter,Depends,HTTPException,Response,Query
from fastapi.responses import JSONResponse
from . import gqtp as g
from .db import connect
from .auth_api import authenticated
from .config import get_settings
router=APIRouter(tags=['transparency'])

@router.get('/transparency/checkpoints')
def checkpoints(limit:int=Query(30,ge=1,le=100),before:int|None=None):
    with closing(connect()) as db:
        rows=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size<? ORDER BY tree_size DESC LIMIT ?', (before if before is not None else 2**63-1,limit)).fetchall()
        return {'items':[json.loads(r[0]) for r in rows]}

@router.get('/transparency/checkpoints/{size}')
def checkpoint(size:int):
    with closing(connect()) as db:
        row=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(size,)).fetchone()
        if not row:raise HTTPException(404,'No signed checkpoint')
        return json.loads(row[0])

@router.get('/transparency/checkpoints/{size}/events')
def public_events(size:int,after:int=Query(0,ge=0),limit:int=Query(500,ge=1,le=1000)):
    with closing(connect()) as db:
        if not db.execute('SELECT 1 FROM gqtp_checkpoints WHERE tree_size=?',(size,)).fetchone():raise HTTPException(404,'No signed checkpoint')
        rows=db.execute('SELECT event_json FROM gqtp_events WHERE seq>? AND seq<=? ORDER BY seq LIMIT ?',(after,size,limit)).fetchall()
        return {'tree_size':size,'items':[json.loads(r[0]) for r in rows]}

@router.get('/transparency/checkpoints/{size}/ots')
def proof_file(size:int):
    with closing(connect()) as db:
        row=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(size,)).fetchone()
        if not row:raise HTTPException(404,'No signed checkpoint')
        f=get_settings().data_dir/'transparency'/'public'/f'checkpoint-{size}.json'
        ots=f.with_suffix('.json.ots')
        if not f.is_file() or f.read_bytes()!=row[0].encode('ascii') or not ots.is_file():raise HTTPException(404,'No exported timestamp proof')
        return Response(ots.read_bytes(),media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="checkpoint-{size}.json.ots"'})

@router.get('/transparency/checkpoints/{size}/file')
def checkpoint_file(size:int):
    # The reference OTS client verifies exact checkpoint bytes; no pretty print.
    with closing(connect()) as db:
        row=db.execute('SELECT envelope_json FROM gqtp_checkpoints WHERE tree_size=?',(size,)).fetchone()
        if not row:raise HTTPException(404,'No signed checkpoint')
        return Response(row[0].encode('ascii'),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="checkpoint-{size}.json"'})

@router.get('/accounts/readings/{consultation_id}/verification')
def private_receipt(consultation_id:str,user:dict=Depends(authenticated)):
    with closing(connect()) as db:
        if not db.execute('SELECT 1 FROM consultations WHERE consultation_id=? AND account_id=? AND status=\'completed\'',(consultation_id,user['account_id'])).fetchone():raise HTTPException(404,'Reading not found')
        if not db.execute('SELECT 1 FROM gqtp_receipts WHERE consultation_id=?',(consultation_id,)).fetchone():raise HTTPException(404,'Verification receipt not yet registered')
        return JSONResponse(g.receipt(db,consultation_id),headers={'Cache-Control':'no-store'})

from .public_inventory import router as _public_inventory_router
router.include_router(_public_inventory_router)
