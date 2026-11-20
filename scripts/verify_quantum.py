#!/usr/bin/env python3
"""Offline artifact and circuit verification. Never authenticates or submits a job."""
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def verify(hashes_only=False):
    manifests={}
    for engine in ('iching','pouch','sticks'):
        base=ROOT/'quantum'/engine; m=json.loads((base/'manifest.json').read_bytes());f=base/m['artifact']
        if hashlib.sha256(f.read_bytes()).hexdigest()!=m['sha256']:raise ValueError(engine+' artifact hash mismatch')
        manifests[engine]=(m,f);print(engine,m['artifact_role'],'SHA-256 PASS')
    from quantum.sticks.recognition import PROFILE_SHA256
    print('Frozen recognition profile:',PROFILE_SHA256)
    if hashes_only:return
    from qiskit import qpy
    from quantum.iching.verification import check_classical_line_truth_table,check_statevector_line,check_full_register_sampled,check_readout_vectors
    from quantum.pouch.circuit import verify_exact_state
    from quantum.pouch.smoke_test import load_verified
    from quantum.sticks.verification import check_decoder,check_logical_circuit,simulate_castings
    from quantum.sticks.hardware import measurement_map,verify_isa
    assert check_classical_line_truth_table() and check_statevector_line() and check_readout_vectors() and check_full_register_sampled()
    with manifests['iching'][1].open('rb') as f: qc,=qpy.load(f)
    assert {r.name:r.size for r in qc.cregs}=={'coins':18,'moves':6}
    print('I Ching ideal mapping and retained artifact shape PASS')
    print('Pouch ideal exact state:',verify_exact_state());load_verified(manifests['pouch'][1]);print('Pouch native metrics PASS')
    assert check_decoder() and check_logical_circuit()
    with manifests['sticks'][1].open('rb') as f: qc,=qpy.load(f)
    verify_isa(qc,measurement_map(qc));assert len(simulate_castings(1))==1
    print('Sticks logical and native product states, mapping, packing and Aer simulation PASS')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--hashes-only',action='store_true');verify(p.parse_args().hashes_only)
