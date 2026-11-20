"""Read SamplerV2 memory without losing per-shot correlations.

This is intentionally separate from QPU submission and financial settlement.
Counts dictionaries are NOT sufficient for matching coin and moving registers
shot-for-shot. Use per-shot BitArray bitstrings from each named register.
"""
from __future__ import annotations
from quantum.iching.medoid import select_medoid, canonical_payload


def decode_register_arrays(coins, moves, *, expected_shots=128):
    """Decode Qiskit register strings (MSB-first) into bottom-to-top bits.

    `coins` and `moves` must be parallel lists with preserved acquisition order.
    `get_bitstrings()` on each named SamplerV2 BitArray supplies this format.
    """
    if not isinstance(coins, list) or not isinstance(moves, list):
        raise ValueError('Per-shot register strings required; counts cannot be used')
    if len(coins) != expected_shots or len(moves) != expected_shots:
        raise ValueError('Incomplete or mismatched IBM shot batch')
    shots = []
    for c,m in zip(coins,moves):
        if not isinstance(c, str) or len(c) != 18 or set(c)-{'0','1'}:
            raise ValueError('Invalid coin register bitstring')
        if not isinstance(m, str) or len(m) != 6 or set(m)-{'0','1'}:
            raise ValueError('Invalid moving register bitstring')
        shots.append({'coin_bits':c[::-1], 'moving_qpu_bits':m[::-1]})
    return shots


def read_sampler_result(result, *, expected_shots=128):
    """Decode a one-PUB SamplerV2 result with named BitArrays."""
    pub=result[0]
    data=pub.data
    coins=data.coins.get_bitstrings()
    moves=data.moves.get_bitstrings()
    return decode_register_arrays(coins,moves,expected_shots=expected_shots)


def analyze_sampler_result(result, *, expected_shots=128):
    return select_medoid(read_sampler_result(result,expected_shots=expected_shots),
                         expected_shots=expected_shots)
