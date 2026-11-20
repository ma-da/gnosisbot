-- Private staged entropy + immutable private recognition archive. Never exposed by HTTP.
CREATE TABLE rune_executions (
 request_id TEXT PRIMARY KEY REFERENCES service_requests(request_id),
 status TEXT NOT NULL CHECK(status IN ('claimed','staged','completed','failed')),
 created_at TEXT NOT NULL,
 staged_json TEXT,
 updated_at TEXT NOT NULL
);
CREATE TABLE rune_private_archives (
 consultation_id TEXT PRIMARY KEY REFERENCES consultations(consultation_id),
 mode TEXT NOT NULL CHECK(mode IN ('pouch','sticks')),
 archive_gzip BLOB NOT NULL,
 archive_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE rune_reading_facts (
 consultation_id TEXT PRIMARY KEY REFERENCES consultations(consultation_id),
 mode TEXT NOT NULL CHECK(mode IN ('pouch','sticks')),
 source TEXT NOT NULL,
 summary_json TEXT NOT NULL,
 completed_at TEXT NOT NULL
);
CREATE INDEX rune_facts_mode_source ON rune_reading_facts(mode,source,completed_at);
