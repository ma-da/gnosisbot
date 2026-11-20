-- Physical measurements stay private; immutable source job/index identity.
CREATE TABLE rune_inventory_batches (
 batch_id TEXT PRIMARY KEY,
 mode TEXT NOT NULL CHECK(mode IN ('pouch','sticks')),
 external_job_id TEXT NOT NULL UNIQUE,
 backend TEXT NOT NULL,
 circuit_sha256 TEXT NOT NULL,
 circuit_version TEXT NOT NULL,
 archive_sha256 TEXT NOT NULL,
 acquired_at TEXT NOT NULL,
 submitted_at TEXT NOT NULL,
 imported_at TEXT NOT NULL,
 item_count INTEGER NOT NULL CHECK(item_count>0),
 status TEXT NOT NULL DEFAULT 'quarantined' CHECK(status IN ('quarantined','approved','withdrawn')),
 approved_at TEXT, approved_by TEXT,
 qpu_seconds REAL CHECK(qpu_seconds>0), resource_units REAL CHECK(resource_units>=0)
);
CREATE TABLE rune_inventory_items (
 item_id TEXT PRIMARY KEY,
 batch_id TEXT NOT NULL REFERENCES rune_inventory_batches(batch_id),
 sample_index INTEGER NOT NULL CHECK(sample_index>=0),
 raw_json TEXT NOT NULL,
 raw_sha256 TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('available','held','consumed','void')),
 exclusion_reason TEXT,
 consultation_id TEXT UNIQUE REFERENCES consultations(consultation_id),
 held_at TEXT, consumed_at TEXT,
 UNIQUE(batch_id,sample_index)
);
CREATE INDEX rune_inventory_allocate ON rune_inventory_items(state,batch_id,sample_index);
