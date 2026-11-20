-- Account hub and durable IBM completion notifications. Extend, never replace, M1A contact table.
ALTER TABLE account_contacts ADD COLUMN revoked_at TEXT;
CREATE TABLE account_email_challenges (
  challenge_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  email_encrypted BLOB NOT NULL,
  email_hash TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT
);
CREATE INDEX idx_email_challenges_account ON account_email_challenges(account_id,created_at);
CREATE TABLE gnosis_completion_outbox (
  request_id TEXT PRIMARY KEY REFERENCES service_requests(request_id),
  consultation_id TEXT NOT NULL REFERENCES consultations(consultation_id),
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  contact_id TEXT REFERENCES account_contacts(contact_id),
  status TEXT NOT NULL CHECK(status IN ('awaiting_contact','pending','sending','sent','needs_review')),
  idempotency_key TEXT NOT NULL UNIQUE,
  attempts INTEGER NOT NULL DEFAULT 0,
  claimed_at TEXT,
  provider_message_id TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  sent_at TEXT
);
CREATE INDEX idx_gnosis_outbox_due ON gnosis_completion_outbox(status,created_at);
