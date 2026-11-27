-- Explicit, bounded administrator canary authorization. No public admission.
CREATE TABLE future_auto_permits (
 permit_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 reviewed_seconds REAL NOT NULL, reserve_floor REAL NOT NULL,
 max_jobs INTEGER NOT NULL CHECK(max_jobs BETWEEN 1 AND 10),
 revoked_at TEXT
);
CREATE TABLE future_auto_requests (
 request_id TEXT PRIMARY KEY REFERENCES ibm_future_jobs(request_id),
 permit_id TEXT NOT NULL REFERENCES future_auto_permits(permit_id),
 claimed_at TEXT, paused_reason TEXT, error_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX future_auto_by_permit ON future_auto_requests(permit_id);
