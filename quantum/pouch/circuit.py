"""Strict V2A Elder Futhark oracle: three draws from a shrinking pouch.

Architecture
------------
Three independent five-qubit rank registers (15 logical qubits total):
    past    q[0:5]   -> 24 equally probable ranks, 0..23
    present q[5:10]  -> 23 equally probable ranks, 0..22
    future  q[10:15] -> 22 equally probable ranks, 0..21

Each register prepares the exact positive-amplitude state
    |S_N> = sum(|j>, j=0..N-1) / sqrt(N).
All remaining computational-basis states have zero ideal amplitude.
The three ranks form a product state with 24 * 23 * 22 = 12,144 supported
outcomes. There is no modulo reduction, ideal rejection or inter-register
entanglement. Actual QPU errors can still create out-of-support measurements.

The shrinking pool sizes are encoded in the quantum states; the identities
of previously drawn runes are excluded by the deterministic classical pouch
decoder. The QPU does not perform adaptive identity-dependent removal.

The custom 23-state synthesis preserves the exact state while reducing the
reference Marrakesh compiled depth from 28 to 25. The state-specific rotation
helper is valid only for its known target input, not arbitrary quantum data.
Physical placement is separate from this backend-independent logical circuit.
No IBM connection or execution occurs on import.
"""

from math import sqrt
import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit.library import UniformSuperpositionGate

VERSION = 'strict-v2a-1.0.0'
POSITIONS = ('past', 'present', 'future')
POOL_SIZES = (24, 23, 22)
N_QUBITS = 15


def _cry_open_on_one(qc, theta, control, target):
    """Apply an open-controlled RY to a target known to be in |1>.

    Desired action: when control is |0>, rotate target by theta; when
    control is |1>, leave target unchanged. The control may be in a
    superposition. This one-CZ construction matches that action on a target
    initially in |1>, including relative phase, without implementing the
    full controlled-RY unitary on an arbitrary target state.

    The gate ordering and target-state precondition are essential. Do not
    reorder this helper or reuse it as a general controlled rotation.
    """
    # Convert the open (zero) control into a conventional one control.
    qc.x(control)

    # In the inactive branch the two RY rotations cancel. In the active
    # branch, CZ applies Z to the target; Z reverses the sign of an RY
    # rotation. On |1>, the result is -RY(theta)|1>.
    qc.ry(-theta / 2, target)
    qc.cz(control, target)
    qc.ry(theta / 2, target)

    # Remove that branch-dependent minus sign, then restore the control.
    # The phase correction matters even though only ranks are measured.
    qc.z(control)
    qc.x(control)


def _prepare_23():
    """Prepare the exact five-qubit state supported on ranks 0 through 22.

    Binary decomposition: 23 = 1 + 2 + 4 + 16. Build the four disjoint
    groups from the high ranks down, using probability weights proportional
    to group size. Controlled Hadamards then divide each group's weight
    evenly among its basis states. All 23 amplitudes are positive and equal.

    Qubit k has binary weight 2**k; local q[0] is the least significant bit.
    """
    qc = QuantumCircuit(5, name='strict23_custom')

    # 1. Begin in |10110> = rank 22 (qubits displayed MSB-first).
    qc.x([1, 2, 4])

    # Keep 1/23 probability at rank 22 (q1=1), and rotate the other 22/23
    # into the branch with q1=0. H on q0 in that branch creates a pair.
    qc.ry(-2 * np.arccos(np.sqrt(1 / 23)), 1)
    qc.ch(1, 0, ctrl_state='0')

    # 2. In the q1=0 branch, q2 is still |1>. Keep 2/22 of this branch's
    # weight at ranks 20 and 21 (each 1/23 overall). Route the remaining
    # 20/23 into q2=0; an open-controlled H on q1 forms four sub-branches.
    _cry_open_on_one(qc, -2 * np.arccos(np.sqrt(2 / 22)), 1, 2)
    qc.ch(2, 1, ctrl_state='0')

    # 3. In the q2=0 branch, q4 is still |1>. Keep 4/20 of its weight in
    # ranks 16..19; send the remaining 16/23 to q4=0. The two final
    # open-controlled H gates create the complete 16-state block 0..15.
    _cry_open_on_one(qc, -2 * np.arccos(np.sqrt(4 / 20)), 2, 4)
    qc.ch(4, 2, ctrl_state='0')
    qc.ch(4, 3, ctrl_state='0')

    # Final support: {22}, {20,21}, {16..19}, {0..15}; probability 1/23 each.
    return qc


def build_circuit():
    """Return a fresh, measured, backend-independent strict V2A circuit."""
    q = QuantumRegister(N_QUBITS, 'q')
    registers = [ClassicalRegister(5, name) for name in POSITIONS]
    qc = QuantumCircuit(q, *registers, name='runes_strict_v2a_depth25')

    # 1. Past: a uniform 24-state preparation (three groups of eight).
    qc.append(UniformSuperpositionGate(24, 5), list(q[:5]))

    # 2. Present: the custom exact 23-state preparation. Its state-specific
    # synthesis shortens the validated circuit's critical path.
    qc.compose(_prepare_23(), qubits=list(q[5:10]), inplace=True)

    # 3. Future: a uniform 22-state preparation.
    qc.append(UniformSuperpositionGate(22, 5), list(q[10:15]))

    # The three preparations act on disjoint wires and can execute in
    # parallel. Their semantic draw order is imposed by the rank decoder.
    # Measuring each group into its own register preserves shot alignment.
    for i, reg in enumerate(registers):
        qc.measure(list(q[5 * i:5 * i + 5]), reg)
    return qc


def verify_exact_state(atol=1e-10):
    """Compare every amplitude with the analytic 24 x 23 x 22 target.

    Removing only the final measurements allows exact statevector evaluation
    of the complete 15-qubit circuit (32,768 amplitudes). Unlike a sampled
    histogram, this verifies zero amplitude outside the allowed support
    and the phases and amplitudes of every allowed basis state.
    """
    import numpy as np
    from qiskit.quantum_info import Statevector

    qc = build_circuit()
    state = Statevector.from_instruction(
        qc.remove_final_measurements(inplace=False)
    ).data
    target = np.zeros(2**N_QUBITS, dtype=complex)

    # The three five-bit ranks occupy weights 2**0, 2**5 and 2**10.
    # Only the 12,144 legal triples receive a nonzero target amplitude.
    indices = [
        a + (b << 5) + (c << 10)
        for a in range(24)
        for b in range(23)
        for c in range(22)
    ]
    target[indices] = 1 / sqrt(len(indices))
    error = float(np.max(np.abs(state - target)))
    if error > atol:
        raise RuntimeError(f'Exact-state regression failed: {error}')

    # Fidelity is the squared overlap; floating-point rounding can return
    # a value infinitesimally above one. This is ideal, not QPU fidelity.
    return {
        'max_amplitude_error': error,
        'supported_states': len(indices),
        'ideal_fidelity': float(abs(np.vdot(target, state))**2),
    }
