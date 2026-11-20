# Literary corpus

The authoritative public file is `app/data/interpretations.json`. The release manifest records exact site export hashes, dataset identifiers, sourcing and editorial status. One physical hexagram identity is shared by Taoist and Confucian perspectives and the classical translation. The root fields mirror the default Taoist perspective. The current frontend displays that default; the complete dual-perspective API is available, and the expanded perspective/line UI may be integrated separately without altering casts. No claim is made of comprehensive human approval.

Current release v0.9.0, schema 2.0.0: 64 canonical King Wen patterns, 64 shared classical translations, 128 tradition interpretations, 768 tradition moving-line interpretations, 4 tradition special passages and 192 review records. The received judgments/lines/special passages and Great Image are included; this is not a complete Ten Wings translation. Sources: Zhouyi and historical commentaries of Liu Yiming and Cheng Yi, AI-assisted source/translation/synthesis/correction workflow. All 192 editorial records remain pending final human review. The complete research dataset, source manifests and correction ledger are external editorial artifacts; do not infer that record-level hashes have been independently verified against the master dataset in this repo.

## Update routine

Export a new version in the editorial project with `site/interpretations.json`, `site/hexagrams_catalog.json`, `release_manifest.json` (also accepts all three in the same directory). The source export's catalog formatting must match the API contract (UTF-8, indented 2, CRLF, terminal newline). Keep the editorial project outside the application tree.

```sh
python scripts/update_corpus.py --source /path/to/export --check
# In a development/release checkout, stop its API and worker first.
python scripts/update_corpus.py --source /path/to/export --apply --confirm-stopped
python scripts/test_release.py
```

The updater verifies both file digests and shared identity, cardinality, ordered line structure, special passages, metadata, boolean approval flags and aggregate approval count. A changed release must advance the numeric corpus version. Record hashes are checked for format/preservation, not recomputed without upstream research data. Both files are backed up externally before replace. Keep a consistent Git commit of corpus and manifest; rollback uses the earlier commit or private backup, not the updater's forward-only path. A new schema requires explicit application changes. Restart API to clear cached data, run the live audit, then commit only the two authoritative files. Catalog is generated from the corpus instead of storing a second 1.8 MB copy. The original v0.9.0 demo is physical only and is not rewritten by corpus updates.

`python scripts/audit_corpus.py --live http://localhost:8000` checks complete public catalog and 128 demo details plus landing/private noindex headers; accounts must be enabled for the owner authorization check. `--stored --db PATH` privately audits stored I Ching projections and hashes for existing receipts. Stored reading JSON and provenance JSON remain exact immutable receipt material; only the ordinary presentation is transformed.
