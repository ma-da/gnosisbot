-- M4A. Append-only IBM inventory and persistent Future job tracking.
-- Inventory is not available for sale until verified source data are imported.
CREATE TABLE ibm_inventory_batches (
 batch_id TEXT PRIMARY KEY,
 provider TEXT NOT NULL CHECK(provider='ibm'),
 backend TEXT NOT NULL,
 external_job_id TEXT NOT NULL,
 circuit_sha256 TEXT NOT NULL,
 circuit_version TEXT NOT NULL,
 acquired_at TEXT NOT NULL,
 submitted_at TEXT NOT NULL,
 source_file_sha256 TEXT NOT NULL UNIQUE,
 imported_at TEXT NOT NULL,
 item_count INTEGER NOT NULL CHECK(item_count>=1),
 status TEXT NOT NULL CHECK(status IN ('quarantined','approved','withdrawn')) DEFAULT 'quarantined',
 approved_by TEXT,
 approved_at TEXT,
 notes TEXT
);
CREATE TABLE ibm_inventory_items (
 item_id TEXT PRIMARY KEY,
 batch_id TEXT NOT NULL REFERENCES ibm_inventory_batches(batch_id),
 sample_index INTEGER NOT NULL CHECK(sample_index>=0),
 coin_bits TEXT NOT NULL CHECK(length(coin_bits)=18 AND coin_bits NOT GLOB '*[^01]*'),
 source_record_sha256 TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('available','held','consumed','void')) DEFAULT 'available',
 consultation_id TEXT UNIQUE REFERENCES consultations(consultation_id),
 held_at TEXT,
 consumed_at TEXT,
 UNIQUE(batch_id,sample_index)
);
CREATE INDEX idx_ibm_inventory_available ON ibm_inventory_items(state,batch_id,item_id);
CREATE TABLE ibm_future_jobs (
 request_id TEXT PRIMARY KEY REFERENCES service_requests(request_id),
 status TEXT NOT NULL CHECK(status IN (
  'queued','submitting','submitted','running','result_ready','completed','failed','needs_reconciliation'
 )),
 backend TEXT,
 external_job_id TEXT UNIQUE,
 circuit_sha256 TEXT,
 circuit_version TEXT,
 shots INTEGER CHECK(shots IS NULL OR shots>0),
 submit_claimed_at TEXT,
 submitted_at TEXT,
 last_checked_at TEXT,
 finished_at TEXT,
 failure_code TEXT,
 metadata_json TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX idx_ibm_future_queue ON ibm_future_jobs(status,created_at,request_id);
