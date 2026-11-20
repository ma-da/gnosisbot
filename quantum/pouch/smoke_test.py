"""Verify the frozen rune circuit and calibrated hardware artifact.

Offline by default. Explicit --submit requests a paid 128-shot run;
--recover retrieves an existing job. No automatic hardware fallback or retry.
The QPY and job receipt must be kept with the local experiment files.
"""

import argparse
import hashlib
import json
from pathlib import Path
from .circuit import verify_exact_state, VERSION
from .decoder import decode_result, decode_ranks
from itertools import product

# Backend preference is policy, not an automatic fallback implementation.
# Each device requires its own validated native circuit and physical layout.
BACKEND_PRIORITY = ('ibm_marrakesh', 'ibm_fez', 'ibm_kingston')
BACKEND = BACKEND_PRIORITY[0]
QPY_NAME = 'runes_strict_v2a_calibrated_ibm_marrakesh.qpy'
EXPECTED_HASH = 'f987202e9fc45236ca92aae6c6f2786a30ee656d6c23a2fc0f11d465f741a27a'
EXPECTED_OPS = {'sx': 56, 'rz': 47, 'measure': 15, 'cz': 11, 'x': 4}
SHOTS = 128
JOB_FILE = Path('runes_production_smoke_128_job.json')


def load_verified(path):
    """Load the exact hardware-tested ISA, checking its bytes and structure.

    QPY stores the native gate sequence and calibrated physical wire mapping.
    Matching the hash is stronger than matching depth and gate counts alone.
    """
    from qiskit import qpy
    import io

    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_HASH:
        raise RuntimeError('QPY hash differs from the tested calibrated circuit')
    circuits = qpy.load(io.BytesIO(raw))
    if len(circuits) != 1:
        raise RuntimeError('Expected one circuit')
    isa = circuits[0]
    if (
        isa.depth() != 25
        or dict(isa.count_ops()) != EXPECTED_OPS
        or isa.depth(filter_function=lambda i: len(i.qubits) == 2) != 6
        or [(r.name, r.size) for r in isa.cregs]
        != [('past', 5), ('present', 5), ('future', 5)]
    ):
        raise RuntimeError('Unexpected ISA metrics')
    return isa


def main():
    """Run ideal-state and decoder regression, then optional IBM execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qpy', type=Path, default=Path(__file__).with_name("marrakesh.qpy"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        '--submit', action='store_true', help='Submit exactly one new 128-shot IBM job'
    )
    modes.add_argument(
        '--recover', action='store_true', help='Retrieve existing smoke-test job'
    )
    args = parser.parse_args()

    # 1. Verify the frozen logical circuit and every legal ordered draw.
    print(VERSION, verify_exact_state())
    triples = {
        tuple(decode_ranks(r)) for r in product(range(24), range(23), range(22))
    }
    assert len(triples) == 12144 and all(len(set(t)) == 3 for t in triples)
    print('Ordered-pool mapping: PASS')

    # 2. Use the previously tested physical circuit, not a new compilation.
    isa = load_verified(args.qpy)
    print('Validated calibrated QPY:', EXPECTED_HASH)
    if not (args.submit or args.recover):
        print('Offline checks passed. No IBM job submitted.')
        return

    # 3. Contact IBM only after an explicit command-line opt-in.
    from qiskit_ibm_runtime import QiskitRuntimeService

    service = QiskitRuntimeService()
    if args.recover:
        receipt = json.loads(JOB_FILE.read_text())
        if (receipt['backend'], receipt['sha256'], receipt['shots']) != (
            BACKEND, EXPECTED_HASH, SHOTS
        ):
            raise RuntimeError('Receipt does not match expected smoke test')
        job = service.job(receipt['job_id'])
    else:
        if JOB_FILE.exists():
            raise RuntimeError('Receipt already exists; use --recover, do not resubmit')
        backend = service.backend(BACKEND)

        # Check that current backend hardware still supports every native gate
        # on the saved physical wires. Do not silently reroute or recompile.
        for inst in isa.data:
            qargs = tuple(isa.find_bit(q).index for q in inst.qubits)
            if not backend.target.instruction_supported(
                operation_name=inst.operation.name, qargs=qargs
            ):
                raise RuntimeError(
                    f'Current backend does not support {inst.operation.name} {qargs}'
                )

        from qiskit_ibm_runtime.executor_sampler import Sampler

        sampler = Sampler(mode=backend)
        # Retain the hardware configuration used in the accepted baseline.
        sampler.options.twirling.enable_gates = False
        sampler.options.twirling.enable_measure = False
        sampler.options.dynamical_decoupling.enable = False
        sampler.options.execution.init_qubits = True

        # Reserve the receipt before submission; ambiguous failure must be
        # checked manually. This prevents a blind second paid submission.
        with JOB_FILE.open('x', encoding='utf-8') as f:
            json.dump({
                'status': 'submitting',
                'backend': BACKEND,
                'sha256': EXPECTED_HASH,
                'shots': SHOTS,
            }, f)
        job = sampler.run([isa], shots=SHOTS)
        receipt = {
            'job_id': job.job_id(),
            'backend': BACKEND,
            'sha256': EXPECTED_HASH,
            'shots': SHOTS,
        }
        temp = JOB_FILE.with_suffix('.tmp')
        temp.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        temp.replace(JOB_FILE)

    # 4. Preserve every shot, including invalid ranks, for later auditing.
    print('IBM job:', job.job_id(), flush=True)
    records = decode_result(job.result()[0])
    if len(records) != SHOTS:
        raise RuntimeError('Unexpected shot count')
    n = sum(r['valid'] for r in records)
    print(f'Valid: {n}/{len(records)} ({n / len(records):.2%})')
    out = {
        'backend': BACKEND,
        'job_id': job.job_id(),
        'sha256': EXPECTED_HASH,
        'records': records,
    }
    Path(f'runes_production_smoke_{job.job_id()}.json').write_text(
        json.dumps(out, indent=2), encoding='utf-8'
    )


if __name__ == '__main__':
    main()
