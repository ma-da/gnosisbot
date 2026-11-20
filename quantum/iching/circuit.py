"""Reference 24-qubit I Ching circuit.

One six-line reading: 18 coin qubits and six moving-line flag qubits.

"""

from __future__ import annotations

N_LINES = 6
N_COINS = 18
N_FLAGS = 6
N_QUBITS = 24

def build_circuit():
    """24-qubit independent three-coin QPU with coherent moving computation.

    Changing flag == 1 if three coins are all equal (000 or 111).
    For each line: compute d1=a XOR b, d2=a XOR c, mark when d1=d2=0,
    then restore coin qubits before measurement. Uses one CCX per line.
    """
    from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
    coin=QuantumRegister(N_COINS,'coin')
    move=QuantumRegister(N_FLAGS,'moving')
    outcoin=ClassicalRegister(N_COINS,'coins')
    outmove=ClassicalRegister(N_FLAGS,'moves')
    qc=QuantumCircuit(coin,move,outcoin,outmove,name='iching_now_becoming_24q')
    qc.h(coin)
    for i in range(N_LINES):
        a,b,c=coin[3*i:3*i+3];m=move[i]
        qc.cx(a,b);qc.cx(a,c)
        qc.x(b);qc.x(c)
        qc.ccx(b,c,m)
        qc.x(b);qc.x(c)
        qc.cx(a,c);qc.cx(a,b)
    qc.measure(coin,outcoin)
    qc.measure(move,outmove)
    return qc

def now_and_becoming(coin_bits: str, moving_qpu_bits: str | None = None):
    """coin_bits: 18 chars ordered [line1coin1...line6coin3] bottom->top.
    moving_qpu_bits: 6 chars ordered from bottom line to top line.
    """
    assert len(coin_bits)==18 and set(coin_bits)<=set('01')
    if moving_qpu_bits is not None:
        assert len(moving_qpu_bits)==6 and set(moving_qpu_bits)<=set('01')
    now=[]; become=[]; lines=[]
    for i in range(6):
        cb=coin_bits[3*i:3*i+3]
        heads=sum(int(x) for x in cb)
        val=6+heads
        moving=int(heads in (0,3))
        now_yang=heads % 2      # 0,1,2,3 heads -> yin, yang, yin, yang
        become_yang=now_yang ^ moving
        read_move=None if moving_qpu_bits is None else int(moving_qpu_bits[i])
        now.append(str(now_yang));become.append(str(become_yang))
        lines.append({
            'position_bottom_to_top':i+1,'coin_bits':cb,'heads':heads,'value':val,
            'now_yang':bool(now_yang),'becoming_yang':bool(become_yang),
            'moving_classically_verified':bool(moving),
            'moving_flag_physically_measured':None if read_move is None else bool(read_move),
            'moving_flag_agrees':None if read_move is None else bool(read_move==moving),
        })
    return {'line_values_bottom_to_top':[r['value'] for r in lines],
        'now_bits_bottom_to_top':''.join(now), 'becoming_bits_bottom_to_top':''.join(become),
        'moving_positions_bottom_to_top':[r['position_bottom_to_top'] for r in lines if r['moving_classically_verified']],
        'lines':lines,
        'moving_flag_matches':None if moving_qpu_bits is None else sum(x['moving_flag_agrees'] for x in lines)}
