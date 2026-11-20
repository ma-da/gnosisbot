"""Circular sticks oracle: independent quantum circumference selections.

One shot prepares four chords. Each endpoint is an eight-qubit register
encoded as a field in one classical register. Eighteen shots yield 72 slots.
All gates are local: no entanglement, conditional operations or postselection.
"""
from __future__ import annotations

VERSION = 'circular-sticks-1.1.0'
POINT_BITS = 8
N_POINTS = 1 << POINT_BITS
BITS_PER_CHORD = 2 * POINT_BITS
CHORDS_PER_SHOT = 4
N_QUBITS = CHORDS_PER_SHOT * BITS_PER_CHORD
SHOTS_PER_CAST = 18
MAX_STICKS = CHORDS_PER_SHOT * SHOTS_PER_CAST
REGISTER = 'cast_bits'
BACKEND_PRIORITY = ('ibm_marrakesh', 'ibm_fez', 'ibm_kingston')


def build_circuit():
    """Prepare |+>^64, then measure every qubit into its matching bit.

    H|0> = (|0> + |1>)/sqrt(2). Eight independent Hadamard qubits
    create 256 equally probable endpoint indices. Two consecutive fields
    form a chord; four such pairs form a shot. Each full bitstring has
    probability 2**(-64) in the ideal circuit. Qubit/bit indices are
    little-endian within each endpoint field.

    No physical timing claim is made about the order of the four chords:
    their replay order is fixed by their classical field indices.
    """
    from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

    q = QuantumRegister(N_QUBITS, 'q')
    out = ClassicalRegister(N_QUBITS, REGISTER)
    qc = QuantumCircuit(q, out, name='elder_futhark_circular_sticks_64q')

    # Prepare independent uniform binary amplitudes on every wire.
    qc.h(q)

    # Measure in the computational basis, preserving bit identity.
    qc.measure(q, out)
    return qc
