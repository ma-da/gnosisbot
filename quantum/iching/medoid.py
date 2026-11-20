"""Canonical 128-shot IBM I Ching medoid, matching clusters.js distance.

No presentation quality bonus, no filtering of mismatching physical flags.
Measured flags are retained as observations but theoretical moving state comes
from the three coin bits, as in quantum.iching.circuit.now_and_becoming.
"""
from __future__ import annotations
import json

ALGORITHM = 'iching_global_medoid_weighted_lines_v1'


def validate_shot(shot):
    if not isinstance(shot, dict):
        raise ValueError('shot must be a dict')
    coin = shot.get('coin_bits')
    move = shot.get('moving_qpu_bits')
    if not isinstance(coin, str) or len(coin) != 18 or set(coin)-{'0','1'}:
        raise ValueError('shot must have 18 bottom-to-top coin bits')
    if not isinstance(move, str) or len(move) != 6 or set(move)-{'0','1'}:
        raise ValueError('shot must have 6 bottom-to-top measured moving bits')
    values = [6 + coin[k:k+3].count('1') for k in range(0, 18, 3)]
    classical_move = ''.join(str(int(v in (6,9))) for v in values)
    return {
        'coin_bits': coin,
        'moving_qpu_bits': move,
        'values': values,
        'moving_positions_bottom_to_top': [i+1 for i, v in enumerate(values) if v in (6, 9)],
        'moving_flag_matches': sum(x == y for x, y in zip(classical_move, move)),
        'moving_classical_bits': classical_move,
    }


def distance(a, b):
    """Mirror clusters.js: 2 for Now yin/yang mismatch, 1 for moving mismatch."""
    va, vb = a['values'], b['values']
    return sum(2 * ((x % 2) != (y % 2)) + ((x in (6,9)) != (y in (6,9)))
               for x, y in zip(va, vb))


def select_medoid(shots, *, expected_shots=128):
    """Return one observed global medoid; preserve all shot indices.

    Ties use the lowest original shot index, matching the existing
    frontend clustering implementation and preserving acquisition order.
    """
    if not isinstance(shots, list) or len(shots) != expected_shots:
        raise ValueError(f'exactly {expected_shots} shots required')
    records = [validate_shot(x) for x in shots]
    distances = [[distance(a,b) for b in records] for a in records]
    totals = [sum(row) for row in distances]
    best = min(totals)
    tied = [i for i, value in enumerate(totals) if value == best]
    chosen = tied[0]  # Stable first measured shot among equal medoid scores.
    return {
        'algorithm': ALGORITHM,
        'selected_shot_index': chosen,
        'selected': records[chosen],
        'scores': totals,
        'tie_count': len(tied),
        'shots': records,
        'shots_count': len(records),
    }


def canonical_payload(selection):
    """JSON-serializable research record: exactly 128 measurements, one selected."""
    return {
        'schema_version': 'gnosis.ibm_shot_batch.v1',
        'selection_algorithm': selection['algorithm'],
        'selected_shot_index': selection['selected_shot_index'],
        'shots_count': selection['shots_count'],
        'shots': selection['shots'],
        'medoid_distance_sums': selection['scores'],
        'medoid_tie_count': selection['tie_count'],
    }


def serialize_payload(selection):
    return json.dumps(canonical_payload(selection), sort_keys=True, separators=(',', ':'))
