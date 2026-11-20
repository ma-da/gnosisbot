-- Operational metadata only. No secrets or private reading payloads.
-- Column order also supports the M5C importer.
CREATE TABLE gnosis_admin_ibm_usage (
 job_id TEXT PRIMARY KEY, qpu_seconds REAL NOT NULL CHECK(qpu_seconds>=0),
 observed_at TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE gnosis_admin_ibm_timing (
 job_id TEXT PRIMARY KEY, measured_seconds REAL NOT NULL CHECK(measured_seconds>=0),
 observed_at TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE gnosis_admin_snapshots (
 name TEXT PRIMARY KEY, payload_json TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE gnosis_admin_btc_checks (
 tree_size INTEGER PRIMARY KEY REFERENCES gqtp_checkpoints(tree_size),
 proof_sha256 TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL,
 status TEXT NOT NULL, checked_at TEXT NOT NULL, block_heights_json TEXT NOT NULL);
