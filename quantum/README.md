# Quantum engines and evidence

The logical circuit, compiled physical circuit, acquisition archive, decoding, and literary interpretation are different objects. A QPY hash fingerprints serialized circuit bytes, not the measurements, a proof of which circuit IBM ran, or a guarantee of future calibration. Do not reserialize retained artifacts merely to update source. Read each `manifest.json` for the artifact role. Hardware evidence below is historical, based on the supplied project and operator qualification; no new IBM job was made for this release.

| Engine | Ideal logical model | Production archive unit | Physical artifact |
| --- | --- | --- | --- |
| I Ching | 18 H-prepared coins + 6 coherent equal-coin flags, 24 qubits | One shot (Past); 128-shot medoid for Future | Retained seed-5 preflight only |
| Pouch | 15 qubits, independent uniform rank supports 24/23/22 | One valid aligned triple | Exact qualified Marrakesh QPY |
| Sticks | 64 independent H preparations, 0 two-qubit gates | 18 consecutive shots = 72 chords | Exact screened Marrakesh QPY |

## Offline verification

From the repository root after installing requirements:

```sh
python scripts/verify_quantum.py --hashes-only
python scripts/verify_quantum.py
python -m unittest discover -s tests -p 'test_*.py'
```

The full verification loads QPY from the repository, checks cryptographic hashes, register structure, exact ideal pouch state, the complete I Ching register mapping using Aer MPS and the sticks product-state native preparation. It checks no network services and submits no QPU task. Qiskit versions matter for QPY loading; use the audited versions. Simulated data are not physical readings. The standalone `quantum.pouch.smoke_test` and `quantum.sticks.hardware` have separately gated hardware operations; never execute a paid submission as part of installation or CI.

Provider adapters, allocation, durable storage and settlement live in `gnosis_platform/`. The I Ching sampler memory decoder and global medoid are in `iching/decoder.py` and `iching/medoid.py`. Rune recognition is deterministic postprocessing on CPU, not part of the QPU circuit. An ideal distribution is not evidence that real measurements are fair, independent, or predictive.

## Entropy sources and holding boundaries

| Source | I Ching | Rune pouch | Circular sticks |
| --- | --- | --- | --- |
| Classic | Local browser cryptographic randomness | Server OS CSPRNG: 24 bytes | Server OS CSPRNG: 144 bytes |
| QCI | Two 16-bit returned words; first 18 MSB-first bits | Twelve 16-bit words | Seventy-two 16-bit words |
| NIST beacon | SHAKE256, first 18 MSB-first bits | SHAKE256, 24 bytes | SHAKE256, 144 bytes |
| IBM Past | Previously measured single shot | Previously measured valid rank triple | Previously measured aligned 18-shot group |
| IBM Future | 128-shot global medoid (implementation gated) | Not enabled | Not enabled |

QCI words are validated as unsigned integers, and rune words are concatenated big-endian in returned order. The I Ching QCI adapter retains both samples in provenance and uses the first 18 bits, grouped bottom-line first. Rune pouch non-QPU casts consume consecutive 5-bit groups MSB first and reject candidates outside the current pool; entropy exhaustion is an explicit failure. Sticks use 18 consecutive 64-bit words with the same slot decoder as hardware measurements. These non-QPU paths do not execute the logical circuits.

NIST uses domain-separated SHAKE256 of a validated 512-bit pulse and the 128-bit server request ID. Domains are `gnosis.iching.nist-beacon-v2.shake256.v1`, `gnosis.runes.pouch.nist-beacon-v2.shake256.v1` and `gnosis.runes.sticks.nist-beacon-v2.shake256.v1`, each followed by a NUL byte. The adapter checks pulse freshness, status, and metadata, not the signature certificate chain. This is deterministic derivation from a shared public beacon, not a new independent physical sample per user.

See `gnosis_platform/qci_qrng.py`, `nist_beacon.py`, `rune_production.py`, `rune_past_inventory.py`, `ibm_worker.py` and `transactions.py` for the actual acquisition, staging and settlement boundaries. Provider failures are not silently substituted with another entropy source. An ambiguous execution is reconciled rather than retried as a new draw. Public code and demonstrations do not include unrevealed commercial inventory or private archives.
