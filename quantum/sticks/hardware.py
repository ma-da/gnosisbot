"""Explicit hardware lifecycle: screen -> holdout -> approve -> execute.

The saved ISA is the production artifact, not a fresh transpilation. Backend
fallback is allowed only before submission and only to approved profiles.
No authentication, network action or job is initiated by importing this file.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .circuit import VERSION, REGISTER, N_QUBITS, SHOTS_PER_CAST, BACKEND_PRIORITY
from .decoder import decode_batch

REFERENCE_HASH = '45cd8d510fb3fa481c38a93ce0b3417175b2f753cce2622248f3e278c6da6d8e'
REFERENCE_JOB = 'dbtuqnc9po4c73ceaot0'
OPTIONS = dict(gate_twirling=False, measurement_twirling=False, dynamical_decoupling=False)
TEMPORARY_EXCLUSIONS = (41, 70, 99, 103)  # Marrakesh historical severe outliers only


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def measurement_map(isa, register=REGISTER, width=N_QUBITS):
    """Recover classical-bit -> physical-wire mapping without using layout metadata."""
    require([(r.name,r.size) for r in isa.cregs] == [(register,width)], 'Unexpected register')
    mapping = {}
    for inst in isa.data:
        if inst.operation.name == 'measure':
            bit = isa.find_bit(inst.clbits[0]).index
            require(bit not in mapping, 'Duplicate measurement')
            mapping[bit] = isa.find_bit(inst.qubits[0]).index
    require(set(mapping) == set(range(width)) and len(set(mapping.values())) == width,
            'Invalid measurement mapping')
    return [mapping[i] for i in range(width)]


def verify_isa(isa, mapping, register=REGISTER, backend=None):
    """Prove each active native wire prepares |+>, up to global phase.

    Product structure means one-qubit statevectors suffice. No 2**64
    allocation; no connectivity requirement. No gates after measurement.
    """
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    w = len(mapping)
    require(w > 0 and measurement_map(isa,register,w) == list(mapping), 'Mapping mismatch')
    require(isa.depth() == 4 and dict(isa.count_ops()) == {'rz':2*w,'sx':w,'measure':w}, 'Unexpected ISA metrics')
    wires = {q: QuantumCircuit(1) for q in mapping}
    measured = set()
    templates = {q: [] for q in mapping}
    if backend is not None:
        require(isa.num_qubits == backend.num_qubits, 'Backend size mismatch')
    for inst in isa.data:
        op = inst.operation
        require(len(inst.qubits)==1 and op.name in {'rz','sx','measure'}, 'Unexpected operation')
        q = isa.find_bit(inst.qubits[0]).index
        require(q in wires and q not in measured, 'Gate outside active preparation')
        if backend is not None:
            require((q,) in backend.target[op.name], f'Unsupported {op.name} on {q}')
        if op.name == 'measure':
            measured.add(q)
        else:
            wires[q].append(op,[0]); templates[q].append(op)
    require(measured == set(mapping), 'Missing measurement')
    for qc in wires.values():
        sv = Statevector.from_instruction(qc).data
        require(abs(abs(sum(sv)/math.sqrt(2))**2-1)<1e-10, 'Native preparation is not |+>')
    first = templates[mapping[0]]
    require(all(g == first for g in templates.values()), 'Native wire templates differ')
    return first


def load_circuit(directory, *, register=REGISTER, backend=None):
    from qiskit import qpy
    d = Path(directory); meta = read_json(d/'manifest.json')
    require(digest(d/'submitted.qpy') == meta['sha256'], 'QPY fingerprint mismatch')
    if backend is not None:
        require(meta['backend'] == backend.name, 'Backend mismatch')
    with (d/'submitted.qpy').open('rb') as f:
        circuits=qpy.load(f)
    require(len(circuits)==1,'Expected one circuit')
    isa=circuits[0]
    verify_isa(isa,meta['physical_qubits_by_classical_bit'],register,backend)
    return isa,meta


def _new_directory(directory):
    d=Path(directory); d.mkdir(parents=True,exist_ok=True)
    if any(d.iterdir()):
        raise FileExistsError(f'Use a new empty directory: {d}')
    return d


def _save_circuit(directory, isa, meta):
    from qiskit import qpy
    d=_new_directory(directory)
    with (d/'submitted.qpy').open('wb') as f: qpy.dump(isa,f)
    meta=dict(meta,sha256=digest(d/'submitted.qpy'),prepared_utc=utc(),
              depth=isa.depth(),operations=dict(isa.count_ops()),options=OPTIONS.copy())
    save_json(d/'manifest.json',meta)
    return meta


def install_reference(source, destination):
    """Install the exact user-validated Marrakesh QPY without reserializing.

    This checks the known hash and original manifest/job ID. It does not read
    results.json or any individual casting. User-reported validation is not
    represented as a new hardware test.
    """
    source=Path(source); isa,meta=load_circuit(source)
    require(meta['backend']=='ibm_marrakesh' and meta['sha256']==REFERENCE_HASH,'Not the validated reference')
    require(len(meta['physical_qubits_by_classical_bit'])==N_QUBITS,'Incorrect production width')
    require((source/'job_id.txt').read_text().strip()==REFERENCE_JOB,'Reference job mismatch')
    require(meta['shots']==2304 and meta['n_castings']==128 and meta['options']==OPTIONS,'Reference settings mismatch')
    d=_new_directory(destination); shutil.copyfile(source/'submitted.qpy',d/'submitted.qpy')
    save_json(d/'manifest.json',dict(meta,version=VERSION,profile=True,validation_job_id=REFERENCE_JOB,
              qualification='user-reported independent holdout; residual significant wire bias acknowledged',
              approved_utc=utc(), flag_for_rescreen=[90,68]))
    return read_json(d/'manifest.json')


def choose_backend(service, profiles_root, name=None):
    """Return (backend, profile directory); skip absent/incompatible profiles.

    Does not select an unvalidated fallback just because it is available.
    """
    require(name is None or name in BACKEND_PRIORITY,'Unknown backend')
    errors=[]
    for candidate in (name,) if name else BACKEND_PRIORITY:
        try:
            p=Path(profiles_root)/candidate
            meta=read_json(p/'manifest.json')
            require(meta.get('profile') is True and meta.get('validation_job_id'),'No approved profile')
            require(len(meta['physical_qubits_by_classical_bit'])==N_QUBITS,'Wrong production width')
            backend=service.backend(candidate)
            require(backend.status().operational,'Backend not operational')
            load_circuit(p,backend=backend)
            return backend,p
        except Exception as exc:
            errors.append(f'{candidate}: {exc}')
    raise RuntimeError('No compatible approved profile: '+'; '.join(errors))


def prepare_job_directory(directory, profile, n_castings=1):
    """Copy the approved QPY unchanged; no job submitted."""
    require(isinstance(n_castings,int) and 1<=n_castings<=1000,'n_castings must be 1..1000')
    profile=Path(profile); _,meta=load_circuit(profile)
    require(meta.get('profile') is True and meta.get('validation_job_id'),'Profile not approved')
    require(len(meta['physical_qubits_by_classical_bit'])==N_QUBITS,'Wrong width')
    d=_new_directory(directory); shutil.copyfile(profile/'submitted.qpy',d/'submitted.qpy')
    meta=dict(meta,profile=False,purpose='casting',version=VERSION,prepared_utc=utc(),
              n_castings=n_castings,shots=n_castings*SHOTS_PER_CAST,options=OPTIONS.copy())
    save_json(d/'manifest.json',meta)
    return meta


def _job_raw(directory, service, *, submit=False, recover_job_id=None, register=REGISTER):
    """Submit exactly once per directory; ambiguous submission requires recovery.

    A manually recovered ID must belong to this exact saved circuit and
    options; the returned backend, register and shot count are checked where
    available but cannot independently attest the circuit behind an arbitrary ID.
    """
    from qiskit_ibm_runtime.executor_sampler import Sampler
    d=Path(directory); isa,meta=load_circuit(d,register=register)
    require(meta['options']==OPTIONS,'Unexpected runtime options')
    jid=d/'job_id.txt'; marker=d/'submission_started'
    if jid.exists():
        saved=jid.read_text().strip()
        require(recover_job_id in (None,saved),'Recovery ID differs from saved ID')
        job=service.job(saved)
    elif recover_job_id:
        job=service.job(recover_job_id)
        with jid.open('x') as f: f.write(job.job_id())
    elif marker.exists():
        raise RuntimeError('Possible existing submission. Recover matching job ID; do not retry.')
    elif not submit:
        raise RuntimeError('Explicit submit=True required')
    else:
        backend=service.backend(meta['backend'])
        require(backend.status().operational,'Backend not operational')
        verify_isa(isa,meta['physical_qubits_by_classical_bit'],register,backend)
        sampler=Sampler(mode=backend)
        sampler.options.twirling.enable_gates=False
        sampler.options.twirling.enable_measure=False
        sampler.options.dynamical_decoupling.enable=False
        with marker.open('x') as f: f.write(utc())
        job=sampler.run([isa],shots=meta['shots'])
        with jid.open('x') as f: f.write(job.job_id())
    print('IBM job ID:',job.job_id(),flush=True)
    if callable(getattr(job,'backend',None)):
        actual=job.backend()
        if actual is not None: require(actual.name==meta['backend'],'Job backend mismatch')
    pubs=job.result(); require(len(pubs)==1,'Expected one result PUB')
    raw=getattr(pubs[0].data,register).get_bitstrings()
    w=len(meta['physical_qubits_by_classical_bit'])
    require(len(raw)==meta['shots'] and all(len(s)==w and set(s)<=set('01') for s in raw),'Unexpected returned shots')
    return job.job_id(),raw,meta


def execute_or_recover(directory, service, *, submit=False, recover_job_id=None):
    """Return archived raw casting data. No rune recognition or rendering."""
    d=Path(directory); _,meta=load_circuit(d)
    require(meta.get('purpose') in ('casting','holdout'),'Not a casting run')
    require(len(meta['physical_qubits_by_classical_bit'])==N_QUBITS,'Unexpected width')
    require(meta['shots']==meta['n_castings']*SHOTS_PER_CAST,'Invalid shot count')
    path=d/'results.json'
    if path.exists():
        result=read_json(path)
        require(result['manifest']==meta and result['job_id']==(d/'job_id.txt').read_text().strip(),'Archived provenance mismatch')
        require(recover_job_id in (None,result['job_id']),'Recovery ID mismatch')
        return result
    jid,raw,meta=_job_raw(d,service,submit=submit,recover_job_id=recover_job_id)
    result=dict(manifest=meta,job_id=jid,source='ibm_qpu',retrieved_utc=utc(),castings=decode_batch(raw,width=N_QUBITS))
    save_json(path,result)
    return result


def calibration_candidates(backend):
    """Calibration filters usable wires; empirical balance ranks survivors."""
    rows=[]
    for q in range(backend.num_qubits):
        try:
            if any((q,) not in backend.target[g] for g in ('rz','sx','measure')): continue
            errors=[float(backend.target[g][(q,)].error) for g in ('sx','measure')]
            if all(math.isfinite(e) and 0<=e<1 for e in errors): rows.append(dict(physical=q,calibration_cost=sum(errors)))
        except (KeyError,ValueError,TypeError,AttributeError): continue
    return rows


def make_isa(backend, mapping, register=REGISTER, template=None):
    """Build native local Hadamards on specified physical wires.

    RZ(pi/2), SX, RZ(pi/2) acts as H up to global phase. If provided,
    use the exact template extracted from the tested Marrakesh reference.
    """
    from qiskit import QuantumCircuit, ClassicalRegister
    from qiskit.circuit.library import RZGate, SXGate
    if template is None: template=[RZGate(math.pi/2),SXGate(),RZGate(math.pi/2)]
    qc=QuantumCircuit(backend.num_qubits,name=f'circular_sticks_{register}_{len(mapping)}q')
    out=ClassicalRegister(len(mapping),register); qc.add_register(out)
    for bit,q in enumerate(mapping):
        for gate in template: qc.append(gate,[q])
        qc.measure(q,out[bit])
    verify_isa(qc,mapping,register,backend)
    return qc


def prepare_screen(directory, backend, *, shots=2048, reference=None):
    """Screen all calibrated usable wires, not just the 64 selected later."""
    require(backend.name in BACKEND_PRIORITY,'Unsupported backend')
    require(isinstance(shots,int) and shots>=2048,'Use at least 2048 screen shots')
    rows=calibration_candidates(backend); mapping=[r['physical'] for r in rows]
    require(len(rows)>=N_QUBITS,'Insufficient usable wires')
    template=None
    if reference is not None:
        ref,rm=load_circuit(reference); template=verify_isa(ref,rm['physical_qubits_by_classical_bit'])
    isa=make_isa(backend,mapping,'screen_bits',template)
    return _save_circuit(directory,isa,dict(version=VERSION,purpose='screen',backend=backend.name,shots=shots,
                         physical_qubits_by_classical_bit=mapping,calibration=rows))


def execute_screen(directory,service,*,submit=False,recover_job_id=None):
    """Persist counts only. Screening measurements never become readings."""
    d=Path(directory); _,meta=load_circuit(d,register='screen_bits')
    require(meta['purpose']=='screen','Not a screen run')
    path=d/'screen_report.json'
    if path.exists():
        report=read_json(path)
        require(report['sha256']==meta['sha256'] and report['job_id']==(d/'job_id.txt').read_text().strip(),'Screen provenance mismatch')
        return report
    jid,raw,meta=_job_raw(d,service,submit=submit,recover_job_id=recover_job_id,register='screen_bits')
    w=len(meta['physical_qubits_by_classical_bit']); values=[int(s,2) for s in raw]
    n=len(raw); rows=[]
    for i,row in enumerate(meta['calibration']):
        ones=sum((v>>i)&1 for v in values)
        rows.append(dict(row,ones=ones,fraction=ones/n,abs_bias=abs(ones/n-.5)))
    report=dict(job_id=jid,backend=meta['backend'],sha256=meta['sha256'],shots=n,wires=rows)
    save_json(path,report); return report


def select_screened(report,*,max_bias=.04,exclude=()):
    """Predeclare selection rule before looking at independent holdout data."""
    require(0<max_bias<=.5,'Invalid screening threshold')
    rows=sorted([r for r in report['wires'] if r['physical'] not in exclude and r['abs_bias']<=max_bias],
                key=lambda r:(r['abs_bias'],r['calibration_cost'],r['physical']))
    require(len(rows)>=N_QUBITS,'Fewer than 64 eligible wires; do not submit holdout')
    require(len({r['physical'] for r in rows})==len(rows),'Duplicate screened wires')
    return rows[:N_QUBITS]


def prepare_holdout(directory,screen_directory,backend,*,n_castings=128,max_bias=.04,exclude=None):
    """Freeze a fresh layout from screening; never tune it on holdout results."""
    require(isinstance(n_castings,int) and n_castings>=128,'Use at least 128 holdout castings')
    s=Path(screen_directory); ref,meta=load_circuit(s,register='screen_bits',backend=backend)
    report=read_json(s/'screen_report.json')
    require(report['sha256']==meta['sha256'] and report['job_id']==(s/'job_id.txt').read_text().strip(),'Screen provenance mismatch')
    exclude=tuple(TEMPORARY_EXCLUSIONS if backend.name=='ibm_marrakesh' else ()) if exclude is None else tuple(exclude)
    selection=select_screened(report,max_bias=max_bias,exclude=exclude); mapping=[r['physical'] for r in selection]
    template=verify_isa(ref,meta['physical_qubits_by_classical_bit'],'screen_bits',backend)
    isa=make_isa(backend,mapping,template=template)
    return _save_circuit(directory,isa,dict(version=VERSION,purpose='holdout',backend=backend.name,
        n_castings=n_castings,shots=n_castings*SHOTS_PER_CAST,physical_qubits_by_classical_bit=mapping,
        screen_job_id=report['job_id'],screen_sha256=meta['sha256'],max_screen_bias=max_bias,
        excluded_physical=list(exclude),calibration=selection))


def approve_holdout(source,destination,*,accept_wire_bias=False):
    """Explicit qualification policy (not a randomness certificate).

    Independent 128+ castings, <=5 percentage-point max wire deviation,
    no Holm-significant geometry/dependence families, no conditional runs
    signal. Significant residual marginal bias requires an explicit waiver.
    No promotion takes place merely because a backend is available.
    """
    from .diagnostics import validate
    source=Path(source); _,meta=load_circuit(source)
    require(meta['purpose']=='holdout' and meta['n_castings']>=128,'Not a qualifying holdout')
    result=read_json(source/'results.json')
    require(result['manifest']==meta and result['job_id']==(source/'job_id.txt').read_text().strip(),'Holdout provenance mismatch')
    require(result['job_id']!=meta['screen_job_id'],'Holdout must be independent of screen')
    report=validate(result)
    require(max(abs(r['fraction']-.5) for r in report['wires'])<=.05,'Max wire bias exceeds 5 percentage points')
    flagged=[t['test'] for t in report['tests'] if t['p_holm_across_tests']<.05]
    residual=[t for t in flagged if t.startswith('Any biased wire') or t=='Pooled bit balance']
    # Fair transition rate is sensitive to marginal bias; conditional runs is
    # additionally checked, but a significant fair-transition test blocks promotion.
    require(len(flagged)==len(residual) and report['conditional_runs_significant']==0,'Geometry/dependence checks failed')
    require(not residual or accept_wire_bias,'Residual wire bias requires explicit approval')
    d=_new_directory(destination); shutil.copyfile(source/'submitted.qpy',d/'submitted.qpy')
    save_json(d/'manifest.json',dict(meta,profile=True,validation_job_id=result['job_id'],approved_utc=utc(),
              qualification='independent holdout; residual bias explicitly accepted' if residual else 'independent holdout',
              flag_for_rescreen=[r['physical'] for r in report['wires'] if r['p_holm']<.05]))
    save_json(d/'validation_report.json',report)
    return read_json(d/'manifest.json')
