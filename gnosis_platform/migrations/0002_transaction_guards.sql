-- Add transaction binding and cooldown ownership without changing prior records.
ALTER TABLE service_requests ADD COLUMN request_hash TEXT;
ALTER TABLE service_requests ADD COLUMN cooldown_until TEXT;
CREATE INDEX idx_service_requests_consultation ON service_requests(consultation_id);
