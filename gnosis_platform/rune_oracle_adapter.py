"""M5A: pure rune processing; never submits, allocates or settles a reading."""
from pathlib import Path
import json
from quantum.pouch.decoder import decode_ranks
from quantum.sticks.decoder import decode_casting
from quantum.sticks.recognition import (
    analyze_casting, public_timeline, PROFILE_SHA256, VERSION as RECOGNITION_VERSION,
)

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'data'
CATALOG = tuple(json.loads((ROOT / 'rune_catalog.json').read_text(encoding='utf8')))
POSITIONS = ('past', 'present', 'future')
DEMO_FILES = {
    'pouch': 'pouch_demo.json',
    'sticks-7': 'sticks_rc1_seed_7.json',
    'sticks-5000': 'sticks_rc1_seed_5000.json',
    'sticks-5001': 'sticks_rc1_seed_5001.json',
}


def pouch_payload(raw_ranks):
    """Process one already selected shot; no random choice or rank repair."""
    ranks = list(raw_ranks)
    ids = decode_ranks(ranks)
    if ids is None:
        raise ValueError('Invalid measured pouch ranks')
    draws = [dict(position=position, rune_id=i, name=CATALOG[i]['name'], glyph=CATALOG[i]['glyph'])
             for position, i in zip(POSITIONS, ids)]
    return {'payload': {'draws': draws}, 'private_audit': {'raw_ranks': ranks, 'rune_ids': ids}}


def sticks_payload(raw_bitstrings):
    """Production reference width only; legacy inventory needs separate approval."""
    casting = decode_casting(raw_bitstrings, width=64)
    timeline = analyze_casting(casting)
    public_casting = {key: value for key, value in casting.items() if key != 'raw_bitstrings_msb_first'}
    return {'payload': {'casting': public_casting, 'timeline': public_timeline(timeline)},
            'private_audit': {'casting': casting, 'recognition': timeline},
            'recognition_version': RECOGNITION_VERSION, 'profile_sha256': PROFILE_SHA256}


def demo_catalog():
    return [{'fixture_id': k, 'mode': 'pouch' if k == 'pouch' else 'sticks',
             'source': 'synthetic_demo', 'delivery': 'demo'} for k in DEMO_FILES]


def load_demo(fixture_id):
    """Fixed allowlist; never accept paths or look at protected inventory."""
    if fixture_id not in DEMO_FILES:
        raise KeyError(fixture_id)
    data = json.loads((ROOT / 'demos' / DEMO_FILES[fixture_id]).read_text(encoding='utf8'))
    if (data.get('source'), data.get('delivery'), data.get('status')) != ('synthetic_demo','demo','ready'):
        raise ValueError('Fixture is not an explicitly labeled public demo')
    if data['mode'] == 'sticks' and data['payload']['timeline']['profile_sha256'] != PROFILE_SHA256:
        raise ValueError('Fixture profile mismatch')
    return {'schema_version': 'rune-reading-v0', **data}
