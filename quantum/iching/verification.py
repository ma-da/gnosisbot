"""Offline circuit and full 24-qubit measurement-mapping checks.

Qiskit is required for statevector checks, but not for classical truth tables.
No provider authentication or QPU submission occurs.
"""
from __future__ import annotations

from itertools import product
from .circuit import build_circuit, now_and_becoming


def check_classical_line_truth_table():
    for bits in product((0, 1), repeat=3):
        a, b, c = bits
        b2, c2 = b ^ a, c ^ a
        flag = int(b2 == 0 and c2 == 0)
        assert flag == int(sum(bits) in (0, 3))
        assert (b2 ^ a, c2 ^ a) == (b, c)
    return True


def check_statevector_line():
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    for bits in product((0, 1), repeat=3):
        qc = QuantumCircuit(4)
        for i, value in enumerate(bits):
            if value: qc.x(i)
        qc.cx(0, 1); qc.cx(0, 2)
        qc.x(1); qc.x(2); qc.ccx(1, 2, 3)
        qc.x(1); qc.x(2); qc.cx(0, 2); qc.cx(0, 1)
        result = Statevector.from_instruction(qc)
        flag = int(sum(bits) in (0, 3))
        expected = sum(value << i for i, value in enumerate(bits)) | (flag << 3)
        assert abs(result.data[expected] - 1) < 1e-10
        assert abs(sum(abs(x)**2 for x in result.data) - 1) < 1e-10
    return True


def check_full_register_sampled(shots=96):
    """Check the entire 24-qubit circuit using Aer MPS, not a 2**24 statevector.

    Verify the measured coin/moving registers retain the source register order
    and that every moving flag matches the three corresponding coin bits.
    """
    from qiskit_aer import AerSimulator

    qc = build_circuit()
    assert qc.num_qubits == 24
    assert {r.name: r.size for r in qc.cregs} == {'coins': 18, 'moves': 6}
    simulator = AerSimulator(method='matrix_product_state')
    job = simulator.run(qc, shots=shots, memory=True, seed_simulator=20261115)
    bitstrings = job.result().get_memory()
    assert len(bitstrings) == shots
    observed = set()
    for sample in bitstrings:
        # Classical-register display order: moves[5..0] coins[17..0].
        moving_msb, coins_msb = sample.split()
        assert len(moving_msb) == 6 and len(coins_msb) == 18
        reading = now_and_becoming(coins_msb[::-1], moving_msb[::-1])
        assert reading['moving_flag_matches'] == 6
        observed.add(coins_msb)
    assert len(observed) > 1, 'Hadamard superposition did not produce varied readings'
    return True


def check_readout_vectors():
    """Verify MSB-first Qiskit bitstring reversal into bottom-to-top order."""
    coins = '000' * 6
    moves = '1' * 6
    reading = now_and_becoming(coins, moves)
    assert reading['line_values_bottom_to_top'] == [6] * 6
    assert reading['now_bits_bottom_to_top'] == '000000'
    assert reading['becoming_bits_bottom_to_top'] == '111111'
    assert reading['moving_flag_matches'] == 6
    assert now_and_becoming(''.join(reversed(coins)), moves) == reading
    return True
