# Elder Futhark | Circular Sticks 1.1.0

Production candidate for the 64-active-qubit circular casting engine. This package produces ordered geometric measurements, not recognized runes or interpretations. The included `marrakesh.qpy` exactly matches the validated physical artifact. No authentication credentials or commercial castings are included.

## Quantum contract

| Property | Value |
|---|---|
| Logical circuit | 64 independent Hadamard preparations and measurements |
| Native ISA reference | depth 4; 128 RZ, 64 SX, 64 measurements; zero entangling gates |
| Circumference | 256 equally spaced points, unit radius |
| Packing | 8 bits per endpoint, 16 per chord, 4 chords per shot |
| Complete casting | 18 shots, 72 chord slots, 1,152 bits |
| Backend preference | Marrakesh, Fez, Kingston |
| Runtime options | gate twirling, measurement twirling and dynamical decoupling disabled |

A Hadamard transforms each initially zero qubit into `( |0> + |1> ) / sqrt(2)`. Because the circuit is a tensor product, an ideal 64-bit shot has probability `2**(-64)` per bitstring. Eight measured bits give an endpoint index from 0 through 255. Native RZ/SX/RZ realizes the same preparation up to global phase. The hardware verifier checks each physical wire's state before its measurement; allocating a full 64-qubit statevector is unnecessary.

For shot `s` (zero based), slot `j` (zero through three), bits `16*j ... 16*j+7` encode endpoint A, the next eight endpoint B, with the lowest bit carrying weight one. Qiskit returns MSB-first strings; integer shifts recover the correct fields. Sequence number is `4*s+j+1`. The unit-circle point for index `k` is `(cos(2*pi*k/256), sin(2*pi*k/256))`. Screen Y may be inverted only at rendering time. Width, tolerance, rune templates, and interpretation are outside this engine.

The sequence is the returned shot order followed by field order, not a measured physical collapse chronology. Duplicate chords, shared endpoints, and equal endpoints remain in the record. Equal endpoints count as zero-length slots, not visible sticks. No software-generated randomness, debiasing, replacement sampling, or best-shot selection is applied to live measurements. Mean visible sticks ideally 71.71875. Hardware measurements need not be exactly uniform.

## Offline verification and operator integration

Run `python scripts/verify_quantum.py` from the repository root. The exact included circuit has SHA-256 `45cd8d510fb3fa481c38a93ce0b3417175b2f753cce2622248f3e278c6da6d8e`. Native `verify_isa` derives classical-to-physical mapping directly from measurements and checks each wire's state using one-qubit statevectors. `manifest.json` documents its historical role, not a replacement for the original private acquisition manifest.

```python
from quantum.sticks.circuit import build_circuit
from quantum.sticks.decoder import decode_casting
from quantum.sticks.verification import check_decoder, check_logical_circuit
assert check_decoder() and check_logical_circuit()
# decode_casting(raw_18_bitstrings, width=64) # supplied original measurement strings
```

`hardware.install_reference(source, destination)` is for an operator with the original private `submitted.qpy`, `manifest.json`, and `job_id.txt`. It verifies the original physical mapping, known hash and job metadata; no result bits are read. It is not required to load the offline artifact. `choose_backend`, `prepare_job_directory` and `execute_or_recover` are explicit operator workflows, not HTTP routes. `execute_or_recover(..., submit=True)` can create a paid job; keep it out of routine startup and deployment. A durable `submission_started` marker blocks blind retries. Recover an existing job only with verified original identity; shape/backend alone cannot prove provenance. Only Marrakesh is qualified, not Fez or Kingston. The application Past service allocates qualified archived results; rune Future is disabled.

## Archive / historical compatibility

`decode_casting(raw)` and `decode_batch(raw)` accept either 18 x 64-bit or 9 x 128-bit shots per casting, without changing the original chord order. Decoder recognizes historical version strings `circular-sticks-1.0.0` and `circular-sticks-1.0.0-64q`, and emits `circular-sticks-1.1.0` for new 64-bit castings. For exact archival reconstruction, pass `version=stored_casting['version']`.

Results JSON stores the manifest, job ID, source, retrieval UTC and a list of castings containing `raw_bitstrings_msb_first`, `chords`, sequence, shot and slot indices, endpoint A/B, projected P1/P2, and degeneracy. Retrieval UTC is not the hardware execution timestamp. Keep original job metadata and all raw files. The supplied notebook does not display any individual casting. Your existing 384 validation castings are not copied or modified; keep their separate quality/provenance labels and reveal status in the eventual app.

## Periodic screening and qualification

The equivalent screening primitives are in `hardware.py` (`prepare_screen`, `execute_screen`, `prepare_holdout`, `approve_holdout`). The original research notebook is not part of this runtime repository. It screens all usable native wires with 2,048 shots, filters at a predeclared absolute bias of 4 percentage points, ranks by empirical bias first and calibration cost second, and freezes the best 64. For Marrakesh only, the historical severe outliers 41/70/99/103 are temporarily excluded by default; reassess exclusions on later maintenance. Other devices do not inherit those physical-qubit IDs. Qubits 90/68 are flagged for future re-screening, not automatically replaced. The exact native one-wire sequence can be extracted from the validated reference. A fresh independent 128-casting holdout must be gathered separately; screening data are not readings. Profile promotion requires explicit operator approval. Each operation uses a new directory; completed jobs can be recovered without resubmission.

The **proposed initial qualification policy** is an engineering decision: 128+ fresh castings, maximum measured wire bias <=5 percentage points, no Holm-significant geometry/pair/transition families and zero significant conditional runs tests; a significant pooled or per-wire balance family requires explicit acceptance. It is not a certification of randomness, independence or performance over time. Holdout thresholds should be declared before examining the new data. Do not repeatedly tune on holdout and claim independent validation.

## Reported experimental evidence

All three 128-casting batches were generated by IBM Marrakesh. The following are user-reported observations, not reruns performed by this package.

| Metric | Original 128q | Replacement 128q | Screened 64q |
|---|---:|---:|---:|
| Job ID | dbttuhie8crs738aq2c0 | dbtu64k9po4c73ce9p0g | dbtuqnc9po4c73ceaot0 |
| Pooled ones | 49.50% | 49.71% | 49.79% |
| Worst wire bias (points) | 18.40 | 36.11 | 4.12 |
| Endpoint uniformity raw p | 0.0006191 | 0.04651 | 0.6447 |
| Endpoint uniformity Holm p | 0.003096 | 0.2326 | 1.0 |
| Chord separation raw p | 0.3834 | 0.7732 | 0.8932 |
| Mean length (ideal 1.2732) | 1.2715 | 1.2763 | 1.2763 |
| Mean crossings (ideal 832.17) | 828.90 | 836.22 | 835.09 |
| Degenerates (ideal 36) | 41 | 32 | 41 |

The final reference screened 135 eligible wires and selected 64 with worst screening bias 0.977 points. Independent holdout returned 2,304 shots, 147,456 measured bits, 128 castings, and passed replay integrity. Significant residual wire bias remains (per-family adjusted p=0.005224, overall Holm p=0.04179); physical 90 and 68 measured 45.88% and 46.44% ones. No significant pairwise associations or conditional runs were detected. Successful aggregate geometry tests do not imply perfect fair independent bits. No claim of predictive accuracy or divinatory efficacy is made.

## Files

- `circuit.py` — documented immutable logical construction.
- `decoder.py` — deterministic 64/128-bit decoding, no Qiskit dependency.
- `hardware.py` — native state checks, reference installation, screened profile management, explicit job submission/recovery.
- `verification.py` — exhaustive endpoint and bit-order checks, product-state verification, optional Aer stabilizer test.
- `diagnostics.py` — width-aware aggregate diagnostics, Holm adjustment, conditional runs. Statistical tests use ideal-model assumptions; pooled tests may be sensitive to dependence; no individual geometry is displayed.
- `tests/test_sticks_offline.py` — decoder, selection and synthetic statistical tests.

## Verification in this release

The classical test suite exhaustively checks 65,536 ordered endpoint pairs for each supported width, all 192 walking-one bit positions, deterministic replay across widths, malformed inputs, screening selection, and report generation including detection of deliberately injected pair dependence. Python and notebook syntax were checked. Qiskit/Aer and authenticated hardware testing of this revised package were not available in the packaging environment. Run the repository's `scripts/verify_quantum.py` in your pinned environment before deployment. No new hardware smoke test is necessary for release packaging. The exact reference fingerprint is from the successful user-run holdout, not a newly generated QPY.

## Recognition

The CPU-only [recognition package](recognition/README.md) consumes exactly the decoded ordered chords. Its immutable RC1 calibration profile and recognition rules are independent of provider and unchanged.
