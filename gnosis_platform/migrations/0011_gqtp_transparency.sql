-- GQTP v1; reserve 0010 for the separate rune inventory migration.
CREATE TABLE gqtp_events (
 seq INTEGER PRIMARY KEY CHECK(seq>0), event_json TEXT NOT NULL);
CREATE TABLE gqtp_receipts (
 consultation_id TEXT PRIMARY KEY REFERENCES consultations(consultation_id),
 seq INTEGER NOT NULL UNIQUE REFERENCES gqtp_events(seq),
 opening_json TEXT NOT NULL, nonce_hex TEXT NOT NULL);
CREATE TABLE gqtp_checkpoints (
 tree_size INTEGER PRIMARY KEY CHECK(tree_size>=0), envelope_json TEXT NOT NULL);
CREATE TABLE gqtp_batches (
 job_id TEXT PRIMARY KEY, engine TEXT NOT NULL, batch_id TEXT NOT NULL UNIQUE,
 seq INTEGER NOT NULL REFERENCES gqtp_events(seq), release_checkpoint INTEGER REFERENCES gqtp_checkpoints(tree_size),
 verification_note TEXT);
CREATE TABLE gqtp_items (
 measurement_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES gqtp_batches(job_id),
 item_id TEXT NOT NULL UNIQUE, sample_index INTEGER NOT NULL,
 seq INTEGER NOT NULL UNIQUE REFERENCES gqtp_events(seq), disposition TEXT NOT NULL CHECK(disposition IN ('commercial','demo','excluded')),
 opening_json TEXT NOT NULL, nonce_hex TEXT NOT NULL, UNIQUE(job_id,sample_index));
CREATE TABLE gqtp_deliveries (
 measurement_id TEXT PRIMARY KEY REFERENCES gqtp_items(measurement_id),
 consultation_id TEXT NOT NULL UNIQUE REFERENCES consultations(consultation_id));
CREATE TABLE gqtp_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO gqtp_settings VALUES('inventory_enforced','0');
CREATE TRIGGER gqtp_events_no_update BEFORE UPDATE ON gqtp_events BEGIN SELECT RAISE(ABORT,'immutable GQTP event'); END;
CREATE TRIGGER gqtp_events_no_delete BEFORE DELETE ON gqtp_events BEGIN SELECT RAISE(ABORT,'immutable GQTP event'); END;
CREATE TRIGGER gqtp_receipts_no_update BEFORE UPDATE ON gqtp_receipts BEGIN SELECT RAISE(ABORT,'immutable GQTP receipt'); END;
CREATE TRIGGER gqtp_receipts_no_delete BEFORE DELETE ON gqtp_receipts BEGIN SELECT RAISE(ABORT,'immutable GQTP receipt'); END;
CREATE TRIGGER gqtp_checkpoints_no_update BEFORE UPDATE ON gqtp_checkpoints BEGIN SELECT RAISE(ABORT,'immutable GQTP checkpoint'); END;
CREATE TRIGGER gqtp_checkpoints_no_delete BEFORE DELETE ON gqtp_checkpoints BEGIN SELECT RAISE(ABORT,'immutable GQTP checkpoint'); END;
CREATE TRIGGER gqtp_items_no_update BEFORE UPDATE ON gqtp_items BEGIN SELECT RAISE(ABORT,'immutable GQTP inventory commitment'); END;
CREATE TRIGGER gqtp_items_no_delete BEFORE DELETE ON gqtp_items BEGIN SELECT RAISE(ABORT,'immutable GQTP inventory commitment'); END;
CREATE TRIGGER gqtp_deliveries_no_update BEFORE UPDATE ON gqtp_deliveries BEGIN SELECT RAISE(ABORT,'immutable GQTP delivery'); END;
CREATE TRIGGER gqtp_deliveries_no_delete BEFORE DELETE ON gqtp_deliveries BEGIN SELECT RAISE(ABORT,'immutable GQTP delivery'); END;
CREATE TABLE gqtp_live_jobs (job_id TEXT PRIMARY KEY, consultation_id TEXT NOT NULL UNIQUE REFERENCES consultations(consultation_id));
CREATE TRIGGER gqtp_past_approval_guard BEFORE UPDATE OF status ON ibm_inventory_batches
WHEN NEW.status='approved' AND (SELECT value FROM gqtp_settings WHERE key='inventory_enforced')='1'
AND NOT EXISTS(SELECT 1 FROM gqtp_batches q WHERE q.batch_id=NEW.batch_id AND q.job_id=NEW.external_job_id AND q.release_checkpoint IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'GQTP release required before inventory approval'); END;
CREATE TRIGGER gqtp_past_frozen_insert BEFORE INSERT ON ibm_inventory_items
WHEN EXISTS(SELECT 1 FROM gqtp_batches WHERE batch_id=NEW.batch_id)
BEGIN SELECT RAISE(ABORT,'GQTP batch already committed'); END;
CREATE TRIGGER gqtp_past_frozen_update BEFORE UPDATE OF batch_id,sample_index,coin_bits,moving_qpu_bits,source_record_sha256 ON ibm_inventory_items
WHEN EXISTS(SELECT 1 FROM gqtp_batches WHERE batch_id=OLD.batch_id)
BEGIN SELECT RAISE(ABORT,'GQTP measurement immutable'); END;
CREATE TRIGGER gqtp_past_frozen_delete BEFORE DELETE ON ibm_inventory_items
WHEN EXISTS(SELECT 1 FROM gqtp_batches WHERE batch_id=OLD.batch_id)
BEGIN SELECT RAISE(ABORT,'GQTP measurement immutable'); END;
CREATE TRIGGER gqtp_settings_no_disable BEFORE UPDATE ON gqtp_settings WHEN OLD.key='inventory_enforced' AND OLD.value='1' AND NEW.value<>'1' BEGIN SELECT RAISE(ABORT,'GQTP enforcement cannot be disabled'); END;
CREATE TRIGGER gqtp_settings_no_delete BEFORE DELETE ON gqtp_settings BEGIN SELECT RAISE(ABORT,'GQTP settings immutable'); END;
CREATE TABLE gqtp_qualifications(batch_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);
CREATE TRIGGER gqtp_qualifications_no_update BEFORE UPDATE ON gqtp_qualifications BEGIN SELECT RAISE(ABORT,'qualification immutable'); END;
CREATE TRIGGER gqtp_qualifications_no_delete BEFORE DELETE ON gqtp_qualifications BEGIN SELECT RAISE(ABORT,'qualification immutable'); END;
CREATE TRIGGER gqtp_iching_item_state BEFORE UPDATE OF state ON ibm_inventory_items
WHEN EXISTS(SELECT 1 FROM gqtp_items q WHERE q.item_id=OLD.item_id AND (q.disposition<>'commercial' AND NEW.state<>'void' OR OLD.state IN ('void','consumed') AND NEW.state<>OLD.state))
BEGIN SELECT RAISE(ABORT,'GQTP excluded or consumed sample cannot be recycled'); END;
CREATE TRIGGER gqtp_iching_batch_frozen BEFORE UPDATE OF external_job_id,circuit_sha256,circuit_version,backend,acquired_at,submitted_at,source_file_sha256,item_count ON ibm_inventory_batches
WHEN EXISTS(SELECT 1 FROM gqtp_batches WHERE batch_id=OLD.batch_id)
BEGIN SELECT RAISE(ABORT,'GQTP batch provenance immutable'); END;
