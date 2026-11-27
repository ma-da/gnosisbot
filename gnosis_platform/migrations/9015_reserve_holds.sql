CREATE TABLE gnosis_reserve_holds (
 job_id TEXT PRIMARY KEY, engine TEXT NOT NULL CHECK(engine IN ('iching','pouch','sticks')),
 created_at TEXT NOT NULL, verified_checkpoint INTEGER REFERENCES gqtp_checkpoints(tree_size),
 proof_sha256 TEXT, promoted_at TEXT,
 CHECK ((verified_checkpoint IS NULL)=(proof_sha256 IS NULL)),
 CHECK (promoted_at IS NULL OR verified_checkpoint IS NOT NULL)
);
CREATE TRIGGER gnosis_reserve_no_delete BEFORE DELETE ON gnosis_reserve_holds BEGIN SELECT RAISE(ABORT,'Reserve designation immutable'); END;
CREATE TRIGGER gnosis_reserve_identity BEFORE UPDATE OF job_id,engine,created_at ON gnosis_reserve_holds BEGIN SELECT RAISE(ABORT,'Reserve identity immutable'); END;
CREATE TRIGGER gnosis_reserve_no_rehold BEFORE UPDATE ON gnosis_reserve_holds WHEN OLD.promoted_at IS NOT NULL BEGIN SELECT RAISE(ABORT,'Promoted reserve immutable'); END;
CREATE TRIGGER gnosis_reserve_release_guard BEFORE UPDATE OF release_checkpoint ON gqtp_batches
WHEN NEW.release_checkpoint IS NOT NULL AND EXISTS(SELECT 1 FROM gnosis_reserve_holds WHERE job_id=NEW.job_id AND promoted_at IS NULL)
BEGIN SELECT RAISE(ABORT,'Explicit reserve promotion required'); END;
CREATE TRIGGER gnosis_reserve_ibm_insert BEFORE INSERT ON ibm_inventory_batches
WHEN NEW.status='approved' AND EXISTS(SELECT 1 FROM gnosis_reserve_holds WHERE job_id=NEW.external_job_id AND promoted_at IS NULL)
BEGIN SELECT RAISE(ABORT,'Explicit reserve promotion required'); END;
CREATE TRIGGER gnosis_reserve_ibm_approve BEFORE UPDATE OF status ON ibm_inventory_batches
WHEN NEW.status='approved' AND EXISTS(SELECT 1 FROM gnosis_reserve_holds WHERE job_id=NEW.external_job_id AND promoted_at IS NULL)
BEGIN SELECT RAISE(ABORT,'Explicit reserve promotion required'); END;
CREATE TRIGGER gnosis_reserve_rune_insert BEFORE INSERT ON rune_inventory_batches
WHEN NEW.status='approved' AND EXISTS(SELECT 1 FROM gnosis_reserve_holds WHERE job_id=NEW.external_job_id AND promoted_at IS NULL)
BEGIN SELECT RAISE(ABORT,'Explicit reserve promotion required'); END;
CREATE TRIGGER gnosis_reserve_rune_approve BEFORE UPDATE OF status ON rune_inventory_batches
WHEN NEW.status='approved' AND EXISTS(SELECT 1 FROM gnosis_reserve_holds WHERE job_id=NEW.external_job_id AND promoted_at IS NULL)
BEGIN SELECT RAISE(ABORT,'Explicit reserve promotion required'); END;
CREATE TRIGGER gnosis_reserve_release_insert_guard BEFORE INSERT ON gqtp_batches
WHEN NEW.release_checkpoint IS NOT NULL AND EXISTS(SELECT 1 FROM gnosis_reserve_holds WHERE job_id=NEW.job_id AND promoted_at IS NULL)
BEGIN SELECT RAISE(ABORT,'Explicit reserve promotion required'); END;
