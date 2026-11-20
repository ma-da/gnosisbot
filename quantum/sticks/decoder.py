"""Deterministic geometry and replay; no Qiskit or RNG dependencies.

The 64-bit production shots and historical 128-bit shots encode the same
72 ordered chord slots. No measurement is corrected, discarded or retried.
"""
from __future__ import annotations

import math
from .circuit import VERSION, N_POINTS, N_QUBITS, MAX_STICKS

SUPPORTED_WIDTHS = (64, 128)
LEGACY_VERSION = 'circular-sticks-1.0.0'
VALIDATED_VERSION = 'circular-sticks-1.0.0-64q'


def circle_point(index: int) -> tuple[float, float]:
    """Index 0 at +x, increasing counterclockwise on a unit circle."""
    if not isinstance(index, int) or not 0 <= index < N_POINTS:
        raise ValueError('Endpoint index outside circumference')
    theta = math.tau * index / N_POINTS
    return math.cos(theta), math.sin(theta)


def normalize_bitstring(bitstring: str, width=None) -> str:
    """Qiskit displays a single register MSB first; do not reverse fields."""
    if not isinstance(bitstring, str):
        raise ValueError('Expected binary string')
    if width is None:
        width = len(bitstring)
    if width not in SUPPORTED_WIDTHS or len(bitstring) != width or set(bitstring) - {'0', '1'}:
        raise ValueError(f'Expected {width} binary characters (64 or 128)')
    return bitstring


def decode_shot(bitstring: str, shot_index: int = 0) -> list[dict]:
    """c0..c7 = A, c8..c15 = B; repeat for each chord slot.

    Each endpoint is an independent 8-bit quantum selection ideally.
    Shifts extract the original fields, not a new random sample.
    """
    s = normalize_bitstring(bitstring)
    slots = len(s) // 16
    if not isinstance(shot_index, int) or not 0 <= shot_index < MAX_STICKS // slots:
        raise ValueError('shot_index outside local casting')
    value = int(s, 2)
    chords = []
    for slot in range(slots):
        a = (value >> (slot * 16)) & 255
        b = (value >> (slot * 16 + 8)) & 255
        chords.append(dict(sequence=shot_index * slots + slot + 1,
                           shot_index=shot_index, slot_index=slot,
                           endpoint_a=a, endpoint_b=b,
                           p1=circle_point(a), p2=circle_point(b), degenerate=a == b))
    return chords


def decode_casting(bitstrings, *, version=None, width=None) -> dict:
    """18 x 64 or 9 x 128; keep duplicates and zero-length slots.

    The replay order is returned shot order, then increasing bit field.
    It is not a physical claim about simultaneous measurement timing.
    """
    raw = list(bitstrings)
    if not raw:
        raise ValueError('Empty casting')
    width = len(normalize_bitstring(raw[0], width))
    shots = MAX_STICKS // (width // 16)
    if len(raw) != shots:
        raise ValueError(f'Expected {shots} shots for width {width}')
    for s in raw:
        normalize_bitstring(s, width)
    allowed = (VERSION, VALIDATED_VERSION) if width == 64 else (LEGACY_VERSION,)
    version = version or allowed[0]
    if version not in allowed:
        raise ValueError('Version does not match shot width')
    chords = [c for i, s in enumerate(raw) for c in decode_shot(s, i)]
    deg = sum(c['degenerate'] for c in chords)
    return dict(version=version, point_count=N_POINTS, slots=MAX_STICKS,
                visible_sticks=MAX_STICKS-deg, degenerate_slots=deg,
                raw_bitstrings_msb_first=raw, chords=chords)


def decode_batch(bitstrings, *, version=None, width=None) -> list[dict]:
    """Partition consecutive shots; never shuffle or filter a casting."""
    raw = list(bitstrings)
    if not raw:
        raise ValueError('Empty batch')
    width = len(normalize_bitstring(raw[0], width))
    shots = MAX_STICKS // (width // 16)
    if len(raw) % shots:
        raise ValueError('Incomplete casting in batch')
    return [decode_casting(raw[i:i+shots], version=version, width=width)
            for i in range(0, len(raw), shots)]
