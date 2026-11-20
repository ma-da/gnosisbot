# Gnosis Elder Futhark recognition — 1.0.0 RC1

Deterministic CPU-only geometry recognition extracted from the owner's fully executed V0.10 notebook. The approved RC1 profile is included byte-for-byte and its SHA-256 is verified at import. This package does not execute quantum circuits, allocate readings, select entropy, or interpret rune meanings. It has no external runtime dependencies (Python 3.10+); matplotlib is optional only for the legacy notebook renderer.

## Install and call

Run from the repository root. No credentials are needed.

```python
from quantum.sticks.recognition import analyze_casting, public_timeline, synthetic_demo
# casting = quantum.sticks.decoder.decode_casting(raw_bitstrings)
# timeline = analyze_casting(casting)
# Save timeline privately; send public_timeline(timeline) with the original casting.
example = synthetic_demo(7)  # Explicitly synthetic, not a quantum reading.
```

`analyze_casting` accepts a dictionary with `chords`: a list of 0–72 rows with integer `sequence` (consecutive 1-based), `endpoint_a` and `endpoint_b` (0–255). Optional `point_count` must be 256, `slots` must equal the list length. Production complete readings require 72 slots. Original measurements and order are retained in `casting`. Degenerate or repeated supporting lines are collapsed for geometric recognition only, not in the replay. Points are derived from indices, not optional supplied coordinates. The caller handles provenance and allocation. `public_timeline` omits internal statuses and unreferenced candidates, but retains all IDs referenced by frames/events/compounds. Its step keys are strings for JSON. The public envelope includes the casting separately; do not publish raw bitstrings or private audit metadata unnecessarily.

## Recognition rules

- 24 approved vector variants; 48% minimum formation span, preferred maximum 61% (soft), minimum stroke 7.5% of diameter; per-rune calibrated conformity floors.
- Apply quality before hierarchy; composite precedence and same-rune geometric deduplication are retained. Different overlapping identities may remain independently recognized. One primary highlight per identity; other distinct eligible occurrences counted separately. Empty readings are valid; no rerolls.
- All 73 frames (0–72 for complete castings) preserve chronological presentation changes. Chords use ordered endpoints; highlight intervals are on actual supporting lines. Use the `docs/rune-reading-contract.md` for coordinate mapping.
- Scores are geometric conformity measures, not statistical confidence or evidence of divination. Calibration results are ideal classical simulations, not a guarantee of individual or quantum outcomes.

## Verify

`python -m unittest discover -s tests -p test_rune_recognition.py -v`

`PYTHONPATH=. python scripts/reproduce_rune_holdout.py`. This reproduces the owner's 500-seed holdout, not a new independent holdout. `holdout_reproduction.json` records the result. `app/data/demos/` contains actual calibrated synthetic timelines for seeds 7, 5000 and 5001, not reserved quantum readings. `SOURCE_MAP.md` lists the source cells. Frozen profile bytes are unchanged; legacy notebook helper functions remain internal in `engine.py` to preserve behavior. The public supported interface is in `api.py`.
