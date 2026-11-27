-- Preserve historical canary authorizations; NULL permit denotes production credit funding.
ALTER TABLE future_auto_requests RENAME TO future_auto_requests_9016;
CREATE TABLE future_auto_requests (
 request_id TEXT PRIMARY KEY REFERENCES ibm_future_jobs(request_id),
 permit_id TEXT REFERENCES future_auto_permits(permit_id),
 claimed_at TEXT, paused_reason TEXT, error_count INTEGER NOT NULL DEFAULT 0
);
INSERT INTO future_auto_requests SELECT * FROM future_auto_requests_9016;
DROP TABLE future_auto_requests_9016;
CREATE INDEX future_auto_by_permit ON future_auto_requests(permit_id);
