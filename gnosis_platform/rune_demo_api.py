"""Public synthetic fixtures only, explicitly enabled; no account or IBM access."""
import os
from fastapi import APIRouter, HTTPException, Response
from .rune_oracle_adapter import demo_catalog, load_demo

router = APIRouter(prefix='/api/v1/runes/demo', tags=['rune-demo'])


def require_enabled():
    if os.environ.get('GNOSIS_ENABLE_RUNE_DEMO') != '1':
        raise HTTPException(404, 'Rune demo disabled')


@router.get('/catalog')
def catalog(response: Response):
    require_enabled()
    response.headers['Cache-Control'] = 'no-store'
    return {'schema_version': 'rune-reading-v0', 'fixtures': demo_catalog()}


@router.get('/readings/{fixture_id}')
def reading(fixture_id: str, response: Response):
    require_enabled()
    try:
        data = load_demo(fixture_id)
    except KeyError:
        raise HTTPException(404, 'Unknown synthetic reading') from None
    response.headers['Cache-Control'] = 'no-store'
    return data
