-- Private certificate pilot. No changes to reading settlement, credits or inventory.
CREATE TABLE reading_certificates (
 certificate_id TEXT PRIMARY KEY,
 consultation_id TEXT NOT NULL REFERENCES consultations(consultation_id),
 schema_version TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('quantum_hardware','reading_record')),
 service_id TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL,
 reading_sha256 TEXT NOT NULL,
 provenance_sha256 TEXT NOT NULL,
 gqtp_seq INTEGER NOT NULL,
 checkpoint_size INTEGER NOT NULL,
 copy_version TEXT NOT NULL,
 render_version TEXT NOT NULL,
 asset_png BLOB NOT NULL,
 asset_sha256 TEXT NOT NULL,
 signature_hex TEXT NOT NULL,
 key_id TEXT NOT NULL,
 issued_at TEXT NOT NULL,
 UNIQUE(consultation_id,schema_version)
);
CREATE TRIGGER reading_certificates_no_update BEFORE UPDATE ON reading_certificates BEGIN SELECT RAISE(ABORT,'Immutable certificate'); END;
CREATE TRIGGER reading_certificates_no_delete BEFORE DELETE ON reading_certificates BEGIN SELECT RAISE(ABORT,'Immutable certificate'); END;
