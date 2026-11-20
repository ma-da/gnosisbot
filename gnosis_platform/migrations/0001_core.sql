-- Gnosis foundation. Store UTC timestamps as ISO-8601 strings.
-- All key material stored here is PUBLIC; never persist private signing keys.
CREATE TABLE accounts (
  account_id TEXT PRIMARY KEY,  -- lower-case hex SHA256(raw Ed25519 public key)
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
  account_group TEXT NOT NULL DEFAULT 'standard',
  is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0,1))
);
CREATE TABLE account_keys (
  key_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  algorithm TEXT NOT NULL CHECK(algorithm = 'Ed25519'),
  public_key_b64url TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  revoked_at TEXT
);
CREATE TABLE auth_challenges (
  challenge_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  nonce_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  verifier_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  last_seen_at TEXT
);
CREATE TABLE credit_accounts (
  account_id TEXT PRIMARY KEY REFERENCES accounts(account_id),
  available INTEGER NOT NULL DEFAULT 0 CHECK(available >= 0),
  reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved >= 0)
);
CREATE TABLE credit_ledger (
  entry_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  kind TEXT NOT NULL CHECK(kind IN ('grant','charge','reserve','release','settle','refund','adjustment')),
  available_delta INTEGER NOT NULL,
  reserved_delta INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  consultation_id TEXT,
  source TEXT,
  authorized_by TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE invitations (
  invitation_id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  account_group TEXT NOT NULL,
  credits INTEGER NOT NULL CHECK(credits >= 0),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  redeemed_at TEXT,
  redeemed_by TEXT REFERENCES accounts(account_id),
  revoked_at TEXT
);
CREATE TABLE consultations (
  consultation_id TEXT PRIMARY KEY,
  account_id TEXT REFERENCES accounts(account_id),
  application_id TEXT NOT NULL,
  question TEXT,
  inquiry_style TEXT,
  status TEXT NOT NULL CHECK(status IN ('pending','completed','failed','cancelled')),
  created_at TEXT NOT NULL,
  finished_at TEXT,
  research_publication_consent INTEGER NOT NULL DEFAULT 0 CHECK(research_publication_consent IN (0,1))
);
CREATE TABLE service_requests (
  request_id TEXT PRIMARY KEY,
  consultation_id TEXT NOT NULL REFERENCES consultations(consultation_id),
  service_id TEXT NOT NULL,
  provider TEXT,
  status TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  credits_cost INTEGER NOT NULL CHECK(credits_cost >= 0),
  started_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE TABLE reading_results (
  result_id TEXT PRIMARY KEY,
  consultation_id TEXT NOT NULL UNIQUE REFERENCES consultations(consultation_id),
  schema_version TEXT NOT NULL,
  reading_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE provider_requests (
  provider_request_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES service_requests(request_id),
  provider TEXT NOT NULL,
  external_job_id TEXT,
  status TEXT NOT NULL,
  metadata_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE UNIQUE INDEX provider_job_unique ON provider_requests(provider, external_job_id) WHERE external_job_id IS NOT NULL;
CREATE TABLE account_contacts (
  contact_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  email_encrypted BLOB NOT NULL,
  email_hash TEXT NOT NULL,
  verified_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE notification_outbox (
  notification_id TEXT PRIMARY KEY,
  consultation_id TEXT REFERENCES consultations(consultation_id),
  contact_id TEXT REFERENCES account_contacts(contact_id),
  notification_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  provider_message_id TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT
);
CREATE TABLE payment_orders (
  order_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  provider TEXT NOT NULL DEFAULT 'stripe',
  external_checkout_id TEXT UNIQUE,
  credits INTEGER NOT NULL CHECK(credits > 0),
  amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
  currency TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE payment_events (
  event_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  external_event_id TEXT NOT NULL,
  received_at TEXT NOT NULL,
  processed_at TEXT,
  UNIQUE(provider,external_event_id)
);
CREATE TABLE cooldowns (
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  cooldown_scope TEXT NOT NULL,
  next_eligible_at TEXT NOT NULL,
  PRIMARY KEY(account_id,cooldown_scope)
);
CREATE INDEX idx_consultations_account_created ON consultations(account_id,created_at);
CREATE INDEX idx_notifications_due ON notification_outbox(status,next_attempt_at);
CREATE INDEX idx_provider_requests_job ON provider_requests(external_job_id);
