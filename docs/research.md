# Research data and ethics

The platform collects server-backed service requests, selected readings, provider provenance, raw measurement audit, research consent, and standardized I Ching factual projections. Rune public presentation and restricted raw archive remain separate. Public I Ching distributions summarize primary/relating hexagrams, moving-line patterns and time series; they are aggregate observatory statistics, not individual questions or receipts. Classic I Ching is local and not represented as a server-observed sample. Rune Classic is server-backed. Historical public demonstrations are not ordinary consultations.

Reading resonance is an optional positive endorsement. `reading_resonance.consultation_id` links to the saved result; missing row means never marked, `resonated=1` means marked, `0` means subsequently withdrawn. `first_marked_at` and `updated_at` store UTC timing. A default frown is not a negative rating; missing feedback is not evidence of failure. The history page reads owner state; the `PUT /api/v1/accounts/readings/{id}/resonance` endpoint validates owner, completed state and Origin. It never modifies a signed reading, billable action or research fact. Public dashboard aggregates do not expose feedback yet.

Private JSONL export (outside the checkout):

```sh
umask 077
python -m gnosis_platform.research_export export --output /var/lib/gnosis/private/research-2026.jsonl
```

The restricted output schema `gnosis.research.export.v2` includes raw results, questions, account identifiers, consent, and resonance fields. Manifest and archive hash are recorded; this is not an anonymized public dataset. Check actual consent and deidentify; small cells and combinations can reidentify users. Do not publish private exports or raw unrevealed inventory, including in tests or debugging traces. The signed public GQTP log has independent purpose and limited metadata; explain it in the user-facing privacy policy. Verify policy/retention/withdrawal requirements before public research publication.

Public ink geometry and similarity visualizations reconstruct measured/simulated outcomes. Quantum entropy, physical circuit noise, meaning and user endorsement are distinct variables. Study design should pre-register selection and comparison rules; medoid, single shot and deterministic public beacon modes have different distributions. No evidence of predictive accuracy is established by circuit verification or resonance. Report denominators, missing data, repeated users, elapsed time, multiplicity and measurement bias. Historical reported experimental metrics are documented per engine, not represented as current new validation.
