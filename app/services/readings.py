"""Versioned presentation adapter. No reading is fabricated or modified in storage."""
import json
from functools import lru_cache
from pathlib import Path

DATA=Path(__file__).resolve().parents[1]/'data'

@lru_cache(maxsize=1)
def sample_data():
    return json.loads((DATA/'ibm_demo_128.json').read_text(encoding='utf-8'))

def interpretation_data():
    # Use the validated, version-sensitive corpus cache; no stale demo catalog.
    from .corpus import corpus
    return corpus()


def interpretation_by_number():
    return {int(h['king_wen_number']):h for h in interpretation_data()['hexagrams']}

def reading_at(index:int):
    dataset=sample_data()
    records=dataset['readings']
    if not 0 <= index < len(records):
        raise IndexError('No such demonstration reading')
    reading=records[index]
    idx=interpretation_by_number()
    return {
        'schema_version':'gnosis.reading.v1',
        'mode':'historical_ibm_demo',
        'demo_only':True,
        'reading':reading,
        'interpretations':{
            'now':idx[reading['now']['king_wen_number']],
            'becoming':idx[reading['becoming']['king_wen_number']]
        },
        'provenance':{
            'backend':dataset.get('backend'),
            'job_id':dataset.get('job_id'),
            'shot_index':reading['shot_index'],
            'shot_count':dataset.get('shots'),
            'created_utc':dataset.get('created_utc'),
            'qpu_seconds_for_batch':dataset.get('QPU_seconds'),
            'circuit':dataset.get('circuit_metadata',{}).get('compiled',{}),

        }
    }
