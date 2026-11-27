-- One durable certificate-processing event per newly completed eligible reading.
-- Existing completion outbox remains the sole email ledger. No historical INSERT.
CREATE TABLE reading_completion_events (
 request_id TEXT PRIMARY KEY REFERENCES service_requests(request_id),
 consultation_id TEXT NOT NULL UNIQUE REFERENCES consultations(consultation_id),
 notify_requested INTEGER NOT NULL CHECK(notify_requested IN (0,1)),
 state TEXT NOT NULL CHECK(state IN ('pending','ready','blocked')),
 certificate_id TEXT REFERENCES reading_certificates(certificate_id),
 attempts INTEGER NOT NULL DEFAULT 0,
 last_error TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK(state!='ready' OR certificate_id IS NOT NULL)
);
CREATE INDEX idx_reading_completion_state ON reading_completion_events(state,created_at);
