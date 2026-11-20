#!/usr/bin/env python3
"""Offline 128-shot Aer sanity check; NEVER uses IBM credentials or QPU."""
from pathlib import Path
import json
import sys

# Make direct script invocation from project root work on WSL.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings
from quantum.iching.decoder import decode_register_arrays
from quantum.iching.medoid import select_medoid, canonical_payload


def main():
    from qiskit_aer import AerSimulator
    from quantum.iching.circuit import build_circuit
    qc=build_circuit()
    sim=AerSimulator(method='matrix_product_state')
    result=sim.run(qc,shots=128,seed_simulator=5,memory=True).result()
    # Aer get_memory joins classical registers as "moves coins", MSB-first.
    memory=result.get_memory(qc)
    coins=[];moves=[]
    for row in memory:
        parts=row.split()
        if len(parts)!=2:raise ValueError('Unexpected Aer classical register layout')
        move,coin=parts
        moves.append(move);coins.append(coin)
    shots=decode_register_arrays(coins,moves)
    out=select_medoid(shots)
    assert len(out['shots'])==128
    assert out['selected']['moving_flag_matches']==6 # Aer ideal flag coherence
    print('AER only: 128 shots analyzed; no QPU jobs')
    print('Selected index:',out['selected_shot_index'])
    print('Selected line values:',out['selected']['values'])
    print('Measured flag agreement:',sum(s['moving_flag_matches'] for s in out['shots']),'/768')
    print('Global medoid score:',out['scores'][out['selected_shot_index']])
    print('Research public count: exactly one (selection only)')
    output=get_settings().data_dir/'ibm-medoid-aer-preview.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(canonical_payload(out),indent=2))
    print('Local research fixture:',output)

if __name__=='__main__':main()
