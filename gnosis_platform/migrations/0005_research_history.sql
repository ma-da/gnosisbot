-- M3C research projections and archive catalog. Authoritative readings stay in reading_results.
-- Additive and forward-only. No existing consultation or ledger columns are removed.
CREATE TABLE reading_measurements (
 measurement_id TEXT PRIMARY KEY,
 consultation_id TEXT NOT NULL UNIQUE REFERENCES consultations(consultation_id),
 source_id TEXT NOT NULL,
 measurement_role TEXT NOT NULL DEFAULT 'reading',
 measurement_status TEXT NOT NULL CHECK(measurement_status IN ('raw_retained','derived_bits_only','metadata_only')),
 raw_payload_json TEXT,
 raw_payload_sha256 TEXT,
 provider_metadata_json TEXT NOT NULL,
 sample_count INTEGER,
 bits_per_sample INTEGER,
 recorded_at TEXT NOT NULL
);
CREATE TABLE reading_facts (
 consultation_id TEXT PRIMARY KEY REFERENCES consultations(consultation_id),
 account_id TEXT NOT NULL REFERENCES accounts(account_id),
 research_subject_id TEXT NOT NULL,
 application_id TEXT NOT NULL,
 source_id TEXT NOT NULL,
 primary_mask INTEGER NOT NULL CHECK(primary_mask BETWEEN 0 AND 63),
 relating_mask INTEGER NOT NULL CHECK(relating_mask BETWEEN 0 AND 63),
 moving_mask INTEGER NOT NULL CHECK(moving_mask BETWEEN 0 AND 63),
 moving_count INTEGER NOT NULL CHECK(moving_count BETWEEN 0 AND 6),
 primary_hexagram INTEGER CHECK(primary_hexagram BETWEEN 1 AND 64),
 relating_hexagram INTEGER CHECK(relating_hexagram BETWEEN 1 AND 64),
 line_values_json TEXT NOT NULL,
 completed_at TEXT NOT NULL,
 measurement_id TEXT NOT NULL UNIQUE REFERENCES reading_measurements(measurement_id),
 projection_version TEXT NOT NULL DEFAULT 'gnosis.research.v1'
);
CREATE INDEX idx_reading_facts_time_source ON reading_facts(completed_at,source_id);
CREATE INDEX idx_reading_facts_owner ON reading_facts(account_id,completed_at DESC);
CREATE TABLE research_archives (
 archive_batch_id TEXT PRIMARY KEY,
 period_start TEXT NOT NULL,
 period_end TEXT NOT NULL,
 schema_version TEXT NOT NULL,
 record_count INTEGER NOT NULL,
 storage_uri TEXT NOT NULL,
 manifest_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,
 verification_status TEXT NOT NULL,
 public_release_status TEXT NOT NULL DEFAULT 'internal'
);
