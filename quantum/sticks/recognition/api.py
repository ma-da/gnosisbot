"""Stable JSON-friendly integration boundary. No quantum execution or random selection."""
from copy import deepcopy
from . import engine
VERSION = '1.0.0-rc1'
PROFILE_SHA256 = engine.PROFILE_SHA256

def analyze_casting(casting):
    """Analyze 0..72 consecutive slots. Production readings use exactly 72.

    Original endpoints/order preserved; never modifies input. Supplied p1/p2
    are not trusted by the recognizer. Exact duplicate supporting lines are
    collapsed only for recognition; all original slots stay in casting.
    """
    if not isinstance(casting, dict) or not isinstance(casting.get('chords'), list):
        raise ValueError('Expected a casting object with a chords list')
    n = len(casting['chords'])
    if casting.get('point_count', 256) != 256 or casting.get('slots', n) != n:
        raise ValueError('Invalid circumference or slot count')
    for i, c in enumerate(casting['chords'], 1):
        if not isinstance(c, dict) or type(c.get('sequence')) is not int or c['sequence'] != i:
            raise ValueError('Invalid chord sequence')
        if any(type(c.get(k)) is not int or not 0 <= c[k] < 256 for k in ('endpoint_a','endpoint_b')):
            raise ValueError('Invalid endpoint index')
    return engine.build_reading_timeline(deepcopy(casting))

def public_timeline(timeline):
    """Remove private per-frame status maps and unreferenced candidates.

    Preserve all IDs referenced by public snapshots, events and compounds.
    Return detached JSON-ready data. Casting is separate in the envelope.
    """
    frames = {str(k): {'shown':v['shown'], 'compounds':v['compounds']} for k,v in timeline['frames'].items()}
    ids = set()
    for f in frames.values():
        for s in f['shown'].values():
            ids.add(s['primary_id']); ids.update(s['occurrence_ids'])
        for r in f['compounds']:
            ids.update(r['candidate_ids'])
    for e in timeline['events']:
        for k in ('primary_id','previous_primary_id'):
            if e.get(k): ids.add(e[k])
        ids.update(e.get('parent_ids',[]))
    return deepcopy(dict(profile_sha256=timeline['profile_sha256'], casting_size=timeline['casting_size'],
                        candidates={k:v for k,v in timeline['candidates'].items() if k in ids}, frames=frames,
                        events=timeline['events'], first_shown=timeline['first_shown'], final=frames[str(timeline['casting_size'])]))

def synthetic_demo(seed):
    """Explicitly classical demonstration; never labels output quantum."""
    c=engine.synthetic_casting(seed)
    c.update(point_count=256, slots=len(c['chords']))
    t=analyze_casting(c)
    return dict(reading_id=f'demo-rc1-{seed}',mode='sticks',source='synthetic_demo',delivery='demo',status='ready',
                provenance=dict(recognition_version=VERSION,profile_sha256=PROFILE_SHA256,seed=seed),
                payload=dict(casting=c,timeline=public_timeline(t)))
