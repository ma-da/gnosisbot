-- Ensures a duplicate/retried request cannot contact QCI twice.
-- Other providers retain their ability to have multiple provider attempts.
CREATE UNIQUE INDEX IF NOT EXISTS uq_qci_request_claim
  ON provider_requests(request_id) WHERE provider='qci';
