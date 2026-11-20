# Gnosis Quantum Transparency Protocol (GQTP)

Signed append-only event log, salted commitments, stock release proofs and owner-only verification. The protocol proves commitment/consistency within its model, not unbiased entropy, metaphysical claims, or IBM-origin authentication independently of the operator. Bitcoin timestamping establishes existence of committed bytes by the attestation, not precise execution time.

## Protocol v1

- SHA-256, Ed25519; RFC 9162 Merkle hash construction (0x00 leaf prefix, 0x01 node prefix, split at largest power of two smaller than subtree size). Empty root = SHA256(empty). Event sequence starts at 1; proofs use zero-based index = seq-1. This is **not** a full RFC 9162 CT protocol implementation.
- Serialization: a versioned Python-compatible ASCII JSON profile (`json.dumps(sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)`). No floats in public events (billing decimal quantities are strings). This is intentionally **not RFC 8785/JCS**. Reading/provenance digests hash the exact original saved UTF-8 JSON strings; the receipt supplies those strings. Precommitted engine payloads use the v1 Python serialization, including existing numeric payloads. A non-Python verifier must implement precisely that codec for payload-level checks; use supplied Python verifier for v1.
- Public physical identity hash is SHA256(codec({schema:"gqtp.physical.v1",provider:"ibm",job_id,pub_index:0,shot_start,shot_count})). Sticks ranges are `18 * sample_index` and `18`; pouch/I Ching start = sample index, count=1. Job exclusivity and inventory database uniqueness prevent reimport through different filenames or circuit aliases. Original outcome hash is not a dedup key.
- Commitment = SHA256(ASCII `GQTP1` || byte 0x00 || ASCII `opening` || byte 0x00 || 32-byte secret random nonce || codec(private opening)). The opening binds reading and provenance SHA256, and rune private archive SHA256 where present. Unsalted result digests and nonces are not public.
- Ordered events: `batch_committed` (acquisition facts, operator qualification, inventory totals), `inventory_committed` (physical identifier, disposition and salted commitment), `batch_released` (checkpoint size and verified proof digest), `reading_completed` (server-backed saved result), `reading_delivered` (bound Past physical ID). Correction/withdrawal UI and generalized future engine shot ranges are not implemented yet. Ledger has SQL protection against ordinary update/delete and immutable signed checkpoints; privileged DB owners can edit local infrastructure, so outside witnesses matter.
- Checkpoint signature = Ed25519 over ASCII `GQTP1\0checkpoint\0` with actual NUL bytes, followed by serialized checkpoint object. Checkpoint contains size, root, key, recorded time, digest of previous signed envelope. Verify the trusted public key from an independent source, not merely the embedded value. `verify-log --previous` verifies the prefix by rehashing exported events up to older size; compact CT consistency proofs are a later optimization. Full prefix recomputation and per-checkpoint JSONL files are simple for launch inventory; at high volume switch to segmented exports/compact proofs to avoid quadratic archive growth.
- OTS anchors the exact signed checkpoint file bytes. Verified timestamp proves existence by block time, not that IBM produced a reading before inquiry or that every job was disclosed. Public delivery IDs allow auditing repeated recorded allocations. It cannot prove undisclosed non-ledger activity never took place. Aggregate records have time and job ID; do not disclose consultation identifiers, questions, emails, raw measurements, nonces or user identities. For privacy, do not have customers publish private receipt unless they wish to disclose outcomes.

## HTTP contract

Routes are included through the existing history router (accounts API enabled). All new public endpoints are read-only and expose only signed prefix events; no unsigned pending leaf content leaks. The existing consultation and history envelopes are unchanged.

| GET | Meaning |
|---|---|
| `/api/v1/transparency/checkpoints` | `{items:[{checkpoint:{schema,tree_size,root,public_key,created_at,previous_checkpoint_sha256},signature}]}`, newest first; `limit`, `before` |
| `/api/v1/transparency/checkpoints/N` | Signed envelope by actual size |
| `/api/v1/transparency/checkpoints/N/events?after=0&limit=500` | `{tree_size,items:[...]}`, pagination by last `seq` |
| `/api/v1/transparency/checkpoints/N/file` | Exact bytes signed/exported and timestamped; never reserialize for OTS |
| `/api/v1/transparency/checkpoints/N/ots` | Detached proof bytes, 404 until exported; existence alone does not mean verified |
| `/api/v1/accounts/readings/CONSULTATION_ID/verification` | Owner-only no-store private receipt; 404 if not owned/not registered |

Private response: `{schema,opening,nonce,event,checkpoint,inclusion_path,saved_bytes,inventory_receipt?}`. Before signed checkpoint covers the completion, `checkpoint` and `inclusion_path` are null (committed but not yet signed). `saved_bytes` includes original reading JSON and provenance JSON strings. For Past, `inventory_receipt` is the distinct pre-delivery inclusion proof and opening; owner can verify the delivered payload matches the precommitted decoding. `batch_released` event shows which OTS proof digest was verified before commercial approval. Raw rune private audit stays protected; receipt binds its digest, not the entire audit. The API does not expose the signing key, private inventory or raw archives. Public ledger is independent of research publication consent; it carries no questions or user identifiers. Disclose this use of anonymized service/time/provenance metadata in production policy. Timestamp status must be shown as unavailable/pending/independently verified, not infer confirmation from existence of `.ots`.

Use the Python CLI to verify a saved private receipt independently with the separately pinned public key:

```bash
python scripts/gnosis_transparency.py verify-receipt private-receipt.json --public-key "$PINNED_PUBLIC_KEY"
python scripts/gnosis_transparency.py verify-log checkpoint-N.json events-N.jsonl --public-key "$PINNED_PUBLIC_KEY" --previous checkpoint-M.json
```

The verifier needs `cryptography` and package source, not a database or provider credentials. CLI receipt export is local-only (`receipt ID --out /private/path/receipt.json`), no secret printed. The included admin dashboard reports aggregate operational state; the CLI remains the independent verifier. For receipt files, enforce private permissions and do not store in a web root.


## Operating lifecycle

Use `scripts/gnosis_transparency.py` and `scripts/gnosis_inventory.py`. On an entirely fresh ledger only, initialize a key, enable inventory enforcement, and create a checkpoint. For a migrated ledger **preserve the exact database, signing key and public checkpoint bytes**. Never call init-key to replace an old key. `status` shows actual checkpoint size. `checkpoint`, `stamp N`, and `upgrade N` are explicit operations, not run on startup. Use `--ots /opt/gnosis-ots/bin/ots` before the command; `N` is the actual tree size. No Bitcoin wallet or transaction is needed.

Import and verify existing archives read-only first with `gnosis_inventory.py inspect ENGINE --source PRIVATE_PATH --verify-ibm`. Import requires live verification and `--confirm-api-stopped`; exclude all previously revealed items and retain invalid items as void. Register batches only after checking original IDs, eligibility, and exclusions with `register-batch ENGINE BATCH_ID --confirm-unrevealed`. Signed checkpoint covers those commitments before release; stamp and upgrade with OTS. Automatic approval/release in current admin dashboard occurs only after independent proof verification, existing GQTP enforcement and eligibility. It is not an automatic periodic task. `GNOSIS_BTC_VERIFIER=core` uses local Bitcoin Core; `explorers` verifies matching public block headers from two explorers, proof path and at least six confirmations, weaker than a full node. Unverified or ambiguous proofs remain quarantined. Preserve verified proof bytes. Do not simulate successful results or bypass guards.

To migrate existing commercial stock, transfer it as protected operational state once; do not reimport the same jobs into a second independently serving ledger. Disable old allocation and workers before snapshot/handoff. Use an independent trusted publication of the existing public key to verify checkpoint continuity. Never deploy a second active copy of the inventory.
