# Alpha.1 release validation

The release was reconstructed from the supplied allowlisted source review snapshot, not from a template. This is a candidate for the operator's acceptance testing, not a claim of production certification.

## Completed in the isolated build environment

- 172 Python tests: 170 passed; 2 skipped because Qiskit was unavailable. The initial snapshot had 164 tests with two outdated frontend contract failures. Three tests specific to discarded installer mechanics were retired; eight offline recognition/sticks tests and three corpus updater tests were added. The actual Python application and frontend source were tested rather than a replacement mock application.
- All five Node regression scripts and JavaScript syntax checks passed. The health test fixture was recovered from the earlier health release; it is a test fixture, not live provider state.
- A fresh temporary SQLite database initialized all 13 migrations, creating 46 tables. No real account or inventory database was opened.
- Isolated Uvicorn acceptance: exact reference I Ching catalog, 128 public demo records, sitemap and robots, public vs private Oracle indexing/cache headers, unauthenticated replay rejection, rune and service catalogs. No providers were invoked.
- Byte-for-byte comparison against the source snapshot and staged Git index: the I Ching corpus, public demo, all three QPY artifacts, frozen recognition profile and its digest file, and all 13 original SQL migrations (20 files). Exact artifact fingerprints and roles are in the three quantum manifests. Hash-only verification passed.
- Corpus updater: identical version no-op, rejection of corrupted exports and identity changes, explicit next-version install with backup and rejection of rollback via the forward-only updater.
- Preliminary literal credential scan checked staged text. This is not comprehensive secret or rights clearance.

## Required before the alpha tag and server launch

In the audited Python 3.12 environment, install the recorded pins and run `pip check`, `python scripts/test_release.py` and `python scripts/verify_quantum.py` with no production state or provider credentials. The build environment lacked Qiskit; the full native QPY load and Aer verification, exact pinned dependency installation, browser acceptance, external service connectivity, production systemd/Caddy configuration and deployment on the intended server have not been verified here. The production origin/session protection and real state migration must be tested in the intended environment. No new QPU execution is required by these checks.

The exact I Ching commercial-submission QPY was not included in the source snapshot. Its recorded digest is distinguished from the retained preflight QPY. A newly recompiled circuit is not interchangeable evidence. Existing signing key and ledger are not included and must be preserved separately if migrating state. Review rights, privacy, credential handling, and abuse controls before making the repository or service public. See deployment and security documentation.
