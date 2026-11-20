# Elder Futhark | Quantum rune pouch

**Strict V2A · 1.0.0 · 15 logical qubits**

## Quantum model

The circuit represents three ordered draws from a 24-rune pouch. Each five-qubit register prepares exactly N equally probable computational-basis states (`0` through `N-1`) and zero ideal amplitude elsewhere.

| Register | Qubit indices | Supported ranks | Conditional draw probability |
|---|---|---|---|
| Past | 0–4 | 0–23 | 1/24 |
| Present | 5–9 | 0–22 | 1/23 |
| Future | 10–14 | 0–21 | 1/22 |

The registers are independent. The strict quantum-state preparation gives the changing option-pool sizes; the classical decoder removes selected rune identities from the ordered pouch. All 12,144 ordered readings have equal ideal probability. This is not the adaptive V2B identity-exclusion circuit.

The optimized present register divides its 23 states into groups of 1, 2, 4 and 16. Negative RY rotations assign the correct weights to branches; open-controlled Hadamards distribute those weights; state-specific controlled rotations use a known target input of |1⟩ and a phase correction. The helper is not a general-purpose controlled-RY replacement. See `circuit.py` for the full explanation alongside each gate sequence.

## Files and integration

- `circuit.py`: isolated logical circuit (`build_circuit()`), exact amplitude verification (`verify_exact_state()`).
- `decoder.py`: strict rank validation, ordered removal, shot-aligned result decoding, optional uniform selection among valid measured shots. Rune names, glyphs and interpretations live in the application.
- `smoke_test.py`: offline regression and explicit hardware smoke test.

Import from the repository root. No credentials or submission on import. The code and public interfaces match the original production candidate; this revision changes documentation and formatting only.

```python
from quantum.pouch.circuit import build_circuit, verify_exact_state
from quantum.pouch.decoder import decode_ranks

qc = build_circuit()
print(verify_exact_state())
print(decode_ranks((0, 0, 0)))  # [0, 1, 2], not three copies of rune 0
```

## Validated hardware reference

The supplied notebook output records the following two layouts tested in job `dbts7g1jbrss73a6ujdg`.

| Metric | Reference | Calibrated |
|---|---:|---:|
| Valid readings | 988/1024 (96.48%) | 997/1024 (97.36%) |
| Past out-of-support | 1 | 6 |
| Present out-of-support | 11 | 8 |
| Future out-of-support | 24 | 13 |
| Past chi-square p | 0.1226 | 0.5051 |
| Present chi-square p | 0.7779 | 0.3924 |
| Future chi-square p | 0.8628 | 0.8362 |

The calibrated layout's 128-shot smoke test (`dbtscs9jbrss73a6upgg`) returned 122 valid shots (95.31%). Offline exact-state validation passed with a maximum amplitude error of 1.04e-17; all 12,144 ordered mappings passed. The ideal fidelity slightly above one is floating-point roundoff. Valid-shot rate is not a measure of full quantum-state fidelity or proof of uniformity.

Frozen native reference: depth 25; 2Q depth 6; 11 CZ; 56 SX; 47 RZ; 4 X; 15 measurements.

The exact retained physical circuit is included as `marrakesh.qpy`. SHA-256:

`f987202e9fc45236ca92aae6c6f2786a30ee656d6c23a2fc0f11d465f741a27a`

## Run tests

Use the audited Python 3.12 / Qiskit environment from the repository root. Run the offline check with the included QPY.

```sh
python -m quantum.pouch.smoke_test
```

The retained operator CLI has `--submit` (paid) and `--recover` (retrieve only). Do not run submissions in tests or deployment. Use a dedicated private working directory with PYTHONPATH pointing to the repository for those operations, and require explicit authorization. Recover any ambiguous job instead of retrying. The commercial qualified acquisition recorded in GQTP was job `dbui90tarooc73fk04fg` (124 valid out of 128, 4 void); the earlier validation jobs above are distinct. The production Past allocator uses committed original indices, not the optional secrets-based choice helper.

Backend priority: **Marrakesh → Fez → Kingston**. Only Marrakesh has a validated rune ISA. Do not submit its physical circuit to another device. Use separate validated mappings and hashes, and refresh calibration-aware placement separately from logical circuit development. No automatic fallback, retries, or interpretation are implemented here. See the byte fingerprint in `manifest.json`.
