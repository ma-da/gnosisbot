# I Ching — Now and Becoming

## Logical model: `iching_now_becoming_24q`

One six-line reading has 18 coin qubits and six ancillary moving-flag qubits, all initialized to zero. Each group of three coins is prepared with Hadamard gates. For each bottom-to-top line, with coins a,b,c and flag m:

```text
                 compute XORs       mark equal      uncompute XORs
 a: |0> -- H --●--●---------------------------●--●-- M(coins)
 b: |0> -- H --X-----X------●------X--------------X-- M(coins)
 c: |0> -- H -----X--X------●------X-----------X----- M(coins)
 m: |0> --------------------X------------------------ M(moves)
```

The diagram is schematic; the authoritative sequence in `circuit.py` is H on all coins, CX(a,b), CX(a,c), X(b), X(c), CCX(b,c,m), X(b), X(c), CX(a,c), CX(a,b), then final measurements. This computes `m = NOT(a XOR b) AND NOT(a XOR c)` while restoring the three coin bits. It coherently marks 000 and 111 in each group. Within a line the flag is correlated with the coin state; the six line groups have no intentional cross-group entanglement. There is no physical relating-hexagram register in this 24q design: Becoming is decoded classically. The earlier 90-qubit experimental design is not the production circuit.

For a measured heads count h, value v = 6+h. Now is v mod 2; moving is v in {6,9}; Becoming is Now XOR moving. Ideal per-line probabilities:

| Value | Probability | Now | Becoming | Moving |
| --- | --- | --- | --- | --- |
| 6 | 1/8 | yin | yang | yes |
| 7 | 3/8 | yang | yang | no |
| 8 | 3/8 | yin | yin | no |
| 9 | 1/8 | yang | yin | yes |

Each Now pattern ideally has probability 1/64; the joint Now/Becoming relationship is not two independent casts. Ideal flags always agree with the coin computation. On hardware, measured moving flags can disagree, and these mismatches are observations, not reasons to replace or repair the original shot. Values and transformation always follow measured coins.

## Measurement handling

The `coins` register has 18 bits; `moves` has 6. Qiskit presents each named register MSB first. `decoder.py` uses the aligned `get_bitstrings()` arrays of a single Sampler PUB and reverses each register into bottom-to-top order. It refuses missing/wrong-width data. Counts alone cannot reconstruct cross-register shot correlations. `circuit.now_and_becoming` gives line records and measured/classical agreement. The presentation layer maps bits to King Wen numbers and the current text corpus; it never changes entropy or saved physical measurements.

## Past, Future, demonstration

Past consumes one original sealed sample from qualified committed inventory in predeclared order; duplicate outcome values are distinct physical samples. Future (admin trial only in this alpha) selects the observed global medoid of all 128 shots. For each pair, add 2 for a Now yin/yang mismatch and 1 for moving/stable mismatch at each line; choose the lowest summed distance, ties to smallest original shot index. `medoid.py` does not reward flag agreement or interpretive desirability. This medoid selection is not a uniform draw of a single shot. All measurements remain archived. The public 128-shot demo is separate and has historical curated presentation, not commercial stock. Similarity graphics are classical visualizations, not physical interference measurements.

## Hardware evidence

- Public demo: Marrakesh job `dbqc109abdes73fo08b0`, 128 shots, 712/768 agreeing flags and 80 all-six matches; cleaned literary fields preserve the physical projection exactly (`app/data/demo_migration_report.json`).
- Retained preflight artifact: `preflight.qpy`, seed 5; SHA-256 `6e0ebc37ca5cd1ec906e18996ee1143567d8eb4961389eea2f9d88a364559ff4`.
- Commercial acquisition: job `dbt5dv7q0h0s73bkc5q0`, recorded submitted compilation digest `e813d95573e2a1c43782be827af13d17e78ae0a35612f8cd5e36ad8a0702e5bc`. **The exact submitted QPY is not included or recovered.** `ibm_worker.snapshot_compiled` transpiles against a live backend with optimization level 3 and seed 5, then hashes fresh QPY serialization. The pilot code saved the digest, not the QPY bytes. A different digest may reflect compilation/layout/serialization changes; no claim of equivalence of the two physical artifacts is made. The existing registered inventory and hashes are unchanged.

For future qualified acquisitions retain the exact submitted QPY and original private job manifest, alongside hardware timestamps and raw results, before final release. Do not resubmit to reconstruct this historical evidence. The current runtime's pilot and Future submission interfaces are retained for operator review, not armed by default.

## Reproduce offline

`python scripts/verify_quantum.py` verifies the classical eight-case truth table, exact four-qubit line basis states, full 24-qubit MPS sampled register alignment, and retained preflight register shape and hash. `tests/test_circuit.py`, `test_qiskit_optional.py`, `test_ibm_medoid.py` and `test_corpus.py` exercise decoding, ties, transformation, and public archive invariants. `scripts/ibm_compile_preflight.py` contacts backend metadata and can compile but not submit. `scripts/ibm_hardware_pilot.py` has explicit paid-job gates; `gnosis_platform/ibm_worker.py` contains guarded settlement and recovery. Neither is needed for offline verification.
