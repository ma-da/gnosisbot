#!/usr/bin/env python3
"""Offline IBM backend compilation audit. NEVER submits any quantum job."""
import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path


def digest(qc):
    from qiskit import qpy
    stream = io.BytesIO()
    qpy.dump(qc, stream)
    return hashlib.sha256(stream.getvalue()).hexdigest(), stream.getvalue()


def twoq_depth(qc):
    return qc.depth(filter_function=lambda instruction: len(instruction.qubits) == 2)


def run(names, seeds, output):
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_ibm_runtime import QiskitRuntimeService
    from quantum.iching.circuit import build_circuit
    from quantum.iching.verification import check_statevector_line, check_classical_line_truth_table, check_readout_vectors

    assert check_classical_line_truth_table()
    assert check_statevector_line()
    assert check_readout_vectors()

    source = build_circuit()
    assert source.num_qubits == 24
    assert {r.name: r.size for r in source.cregs} == {'coins': 18, 'moves': 6}
    source_hash, _ = digest(source)

    print('Reference 24-qubit circuit QPY sha256:', source_hash)
    print('Logical gates:', len(source.data), '2Q:', sum(len(i.qubits) == 2 for i in source.data))
    print('IBM Runtime backend metadata only; no QPU jobs will be submitted.')
    service = QiskitRuntimeService()
    records = []
    for name in names:
        backend = service.backend(name)
        if not backend.status().operational:
            print('SKIPPED non-operational backend:', name)
            continue
        for seed in seeds:
            print(f'Compiling {name} seed={seed} ...', flush=True)
            pm = generate_preset_pass_manager(backend=backend, optimization_level=3, seed_transpiler=seed)
            compiled = pm.run(source)
            if compiled.num_clbits != 24:
                raise RuntimeError(f'Classical register size changed: {compiled.num_clbits}')
            cregs = {r.name: r.size for r in compiled.cregs}
            if cregs.get('coins') != 18 or cregs.get('moves') != 6:
                raise RuntimeError(f'Measurement register layout changed: {cregs}')
            h, blob = digest(compiled)
            ops = {str(k): int(v) for k, v in compiled.count_ops().items()}
            record = {
                'backend': name, 'backend_qubits': backend.num_qubits,
                'seed': seed, 'optimization_level': 3,
                'source_qpy_sha256': source_hash,
                'compiled_qpy_sha256': h,
                'compiled_depth': compiled.depth(),
                'two_qubit_depth': twoq_depth(compiled),
                'two_qubit_gates': sum(len(inst.qubits) == 2 for inst in compiled.data),
                'cz_gates': ops.get('cz', 0),
                'total_gates': len(compiled.data),
                'operation_counts': ops,
                'classical_registers': cregs,
                'layout_initial': str(compiled.layout.initial_layout) if compiled.layout else None,
                'layout_final': str(compiled.layout.final_layout) if compiled.layout else None,
            }
            records.append(record)
            print(f"  CZ={record['cz_gates']} 2Q depth={record['two_qubit_depth']} total={record['total_gates']}")
            if output:
                path = Path(output)
                path.mkdir(parents=True, exist_ok=True)
                (path / f'{name}-seed{seed}-{h[:12]}.qpy').write_bytes(blob)
    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'offline_transpile_only',
        'qpu_jobs_submitted': 0,
        'reference_qpy_sha256': source_hash,
        'results': records,
    }
    if output:
        dest = Path(output) / 'ibm_compile_preflight.json'
        dest.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Saved:', dest)
    print(json.dumps([{'backend': r['backend'], 'seed': r['seed'], 'cz': r['cz_gates'], 'twoq_depth': r['two_qubit_depth']} for r in records], indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backends', nargs='+', default=['ibm_marrakesh', 'ibm_fez'])
    p.add_argument('--seeds', nargs='+', type=int, default=[0, 1, 2])
    p.add_argument('--output', default='')
    args = p.parse_args()
    run(args.backends, args.seeds, args.output)
