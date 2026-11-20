"""Public demonstration APIs. No IBM or QRNG calls are made by this service."""
from fastapi import APIRouter, HTTPException
from app.services.readings import sample_data, reading_at, interpretation_data

router = APIRouter(prefix='/api/v1')

@router.get('/health')
async def health():
    return {'status': 'ok', 'reading_provider': 'historical_demo', 'live_qpu': False}

@router.get('/capabilities')
async def capabilities():
    return {
        'standard': {'enabled': True, 'source': 'browser_crypto'},
        'quantum_entropy': {'enabled': False, 'reason': 'ANU QRNG API not yet connected'},
        'quantum_hardware': {'enabled': True, 'source': 'archived_ibm_demo', 'fresh_qpu': False},
    }

@router.get('/hexagrams')
async def hexagrams():
    """Small reference catalog. Symbols and interpretations are public."""
    from app.services.readings import interpretation_data as _authoritative_corpus
    return _authoritative_corpus()['hexagrams']

@router.get('/demo')
async def demo_info():
    d = sample_data()
    return {'count': len(d['readings']), 'job_id': d['job_id'], 'backend': d['backend'],
            'notice': 'Historical IBM measurements for UI development; not a new or sealed quantum throw.'}

@router.get('/demo/catalog')
async def demo_catalog():
    """Summary-only catalog for clustering. Full raw measurements remain in individual readings."""
    d = sample_data()
    return {
        'job_id': d['job_id'], 'count': len(d['readings']),
        'readings': [
            {'index': i, 'shot_index': r['shot_index'],
             'values': r['line_values_bottom_to_top'],
             'now': int(r['now']['king_wen_number']),
             'becoming': int(r['becoming']['king_wen_number']),
             'moving_positions': r['moving_positions_bottom_to_top'],
             'matches': r['moving_flag_matches']}
            for i, r in enumerate(d['readings'])
        ],
    }

@router.get('/demo/readings/{index}')
async def demo_reading(index: int):
    try:
        return reading_at(index)
    except IndexError:
        raise HTTPException(status_code=404, detail='Demonstration reading not found')
