"""Classical interface between quantum rank measurements and rune identities.

The quantum circuit supplies independent uniform ranks in pools of size 24,
23 and 22. Here the ranks index the shrinking ordered pouch of rune IDs.
The mapping is bijective: every ideal rank triple corresponds to exactly one
ordered draw without replacement. Interpretation and glyphs belong elsewhere.
No dependency on Qiskit, IBM credentials or application state is needed.
"""

from numbers import Integral
from secrets import choice

POOL_SIZES = (24, 23, 22)
POSITIONS = ('past', 'present', 'future')


def decode_ranks(ranks):
    """Return three unique ordered rune IDs, or None for an invalid rank.

    Out-of-support hardware measurements are rejected, never wrapped with
    modulo or repaired into plausible values. Each valid rank is a zero-based
    index into the remaining pool, not necessarily the final rune's ID.
    """
    ranks = tuple(ranks)
    if len(ranks) != 3:
        raise ValueError('Expected exactly three ranks')
    if not all(
        isinstance(v, Integral) and not isinstance(v, bool) and 0 <= v < n
        for v, n in zip(ranks, POOL_SIZES)
    ):
        return None

    # pop() returns and removes the indexed rune: 24 -> 23 -> 22 options.
    pouch = list(range(24))
    return [pouch.pop(int(v)) for v in ranks]


def decode_result(pub):
    """Decode one Sampler PUB result while preserving raw data and shot order.

    Each named classical register is a five-bit MSB-first integer string.
    Read the three columns together: never sort or aggregate them separately,
    because the three values from a single shot form one reading.
    """
    columns = [getattr(pub.data, name).get_bitstrings() for name in POSITIONS]
    if len({len(c) for c in columns}) != 1:
        raise ValueError('Unequal register shot counts')

    records = []
    for i, bits in enumerate(zip(*columns)):
        if any(len(s) != 5 or set(s) - {'0', '1'} for s in bits):
            raise ValueError('Expected five measured bits per register')
        raw = [int(s, 2) for s in bits]
        ids = decode_ranks(raw)
        records.append({
            'shot': i,
            'raw_ranks': raw,
            'valid': ids is not None,
            'rune_ids': ids,
        })
    return records


def select_reading(records):
    """Optionally choose one measured valid shot uniformly using secrets.choice.

    This classical selection introduces no preference among valid shot
    indices. It does not eliminate systematic QPU measurement bias and does
    not generate replacement runes when no valid shots are available.
    """
    valid = [r for r in records if r['valid']]
    if not valid:
        raise ValueError('No valid quantum readings')
    return choice(valid)
