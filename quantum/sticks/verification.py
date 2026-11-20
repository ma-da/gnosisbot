"""Offline regression tests; no IBM authentication or network operation."""
from __future__ import annotations

from .circuit import build_circuit, N_QUBITS, REGISTER, SHOTS_PER_CAST
from .decoder import decode_shot, decode_casting, decode_batch, circle_point


def check_decoder():
    """Exhaust all ordered endpoint pairs, walking bits, and both shot widths."""
    for w in (64,128):
        slots=w//16; shots=72//slots
        def pack(pairs):
            return format(sum((a | b<<8) << (16*i) for i,(a,b) in enumerate(pairs)),f'0{w}b')
        for a in range(256):
            for b0 in range(0,256,slots):
                pairs=[(a,b) for b in range(b0,b0+slots)]
                out=decode_shot(pack(pairs))
                assert [(c['endpoint_a'],c['endpoint_b']) for c in out]==pairs
                assert all(c['degenerate']==(c['endpoint_a']==c['endpoint_b']) for c in out)
        for i in range(w):
            out=decode_shot(format(1<<i,f'0{w}b'))
            expected=[(0,0)]*slots; val=1<<(i%8)
            expected[i//16]=(val,0) if i%16<8 else (0,val)
            assert [(c['endpoint_a'],c['endpoint_b']) for c in out]==expected
        raw=pack([(0,255),(1,128),(17,17),(0,255)]*(slots//4))
        cast=decode_casting([raw]*shots)
        assert cast['slots']==72 and cast['visible_sticks']==54
        assert [c['sequence'] for c in cast['chords']]==list(range(1,73))
        assert cast['raw_bitstrings_msb_first']==[raw]*shots
        assert decode_batch([raw]*(2*shots))==[cast,cast]
        for bad in ([raw]*(shots-1), ['x'*w]*shots, [raw]*(shots-1)+['0'*(192-w)]):
            try: decode_casting(bad)
            except ValueError: pass
            else: raise AssertionError('Malformed input accepted')
    assert circle_point(0)==(1.0,0.0)
    # Repack the same 1,152 bits into either width. Geometry identical;
    # shot and slot positions deliberately differ with the packing.
    values=list(range(72)); pairs=[(i,(i*13)%256) for i in values]
    def repack(w):
        slots=w//16
        return [format(sum((a|b<<8)<<(16*j) for j,(a,b) in enumerate(pairs[i:i+slots])),f'0{w}b') for i in range(0,72,slots)]
    a,b=[decode_casting(repack(w)) for w in (64,128)]
    assert [(c['sequence'],c['p1'],c['p2']) for c in a['chords']]==[(c['sequence'],c['p1'],c['p2']) for c in b['chords']]
    return True


def check_logical_circuit():
    """Prove product structure from actual gates, not a 2**64 statevector."""
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    import math
    qc=build_circuit()
    assert qc.num_qubits==qc.num_clbits==N_QUBITS
    assert [(r.name,r.size) for r in qc.cregs]==[(REGISTER,N_QUBITS)]
    assert dict(qc.count_ops())=={'h':N_QUBITS,'measure':N_QUBITS}
    assert qc.depth()==2
    seen_h,seen_m=set(),set()
    for inst in qc.data:
        assert len(inst.qubits)==1
        q=qc.find_bit(inst.qubits[0]).index
        if inst.operation.name=='h':
            assert q not in seen_h and q not in seen_m; seen_h.add(q)
        else:
            assert inst.operation.name=='measure' and q in seen_h and q not in seen_m
            assert qc.find_bit(inst.clbits[0]).index==q; seen_m.add(q)
    assert seen_h==seen_m==set(range(N_QUBITS))
    one=QuantumCircuit(1); one.h(0)
    assert all(abs(a-1/math.sqrt(2))<1e-12 for a in Statevector.from_instruction(one).data)
    return True


def simulate_castings(n_castings=1,seed=20261116):
    """Offline Clifford simulation; simulation is not live quantum data."""
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    if not isinstance(n_castings,int) or n_castings<1: raise ValueError('Positive casting count required')
    simulator=AerSimulator(method='stabilizer')
    qc=transpile(build_circuit(),simulator,optimization_level=0)
    raw=simulator.run(qc,shots=n_castings*SHOTS_PER_CAST,memory=True,seed_simulator=seed).result().get_memory()
    assert len(raw)==n_castings*SHOTS_PER_CAST
    return decode_batch(raw,width=N_QUBITS)
