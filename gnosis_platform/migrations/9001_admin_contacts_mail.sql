-- Dedicated encrypted public contact messages and separately audited manual admin email.
-- The established GNOSIS_CONTACT_ENCRYPTION_KEY protects PII and plaintext bodies.
CREATE TABLE IF NOT EXISTS gnosis_site_contact_messages (
  message_id TEXT PRIMARY KEY,
  name_ciphertext BLOB NOT NULL,
  email_ciphertext BLOB NOT NULL,
  email_digest TEXT NOT NULL,
  message_ciphertext BLOB NOT NULL,
  source TEXT NOT NULL DEFAULT 'homepage',
  created_at TEXT NOT NULL,
  read_at TEXT,
  archived_at TEXT
);
CREATE INDEX IF NOT EXISTS gnosis_site_contact_unread
  ON gnosis_site_contact_messages(archived_at,read_at,created_at DESC);
CREATE INDEX IF NOT EXISTS gnosis_site_contact_rate
  ON gnosis_site_contact_messages(email_digest,created_at DESC);
CREATE TABLE IF NOT EXISTS gnosis_admin_contact_audit (
  audit_id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES gnosis_site_contact_messages(message_id),
  actor_account_id TEXT NOT NULL REFERENCES accounts(account_id),
  action TEXT NOT NULL CHECK(action IN ('mark_read','mark_unread','archive','restore')),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gnosis_admin_manual_emails (
  mail_id TEXT PRIMARY KEY,
  actor_account_id TEXT NOT NULL REFERENCES accounts(account_id),
  from_address TEXT NOT NULL,
  to_ciphertext BLOB NOT NULL,
  subject_ciphertext BLOB NOT NULL,
  body_ciphertext BLOB NOT NULL,
  contact_message_id TEXT REFERENCES gnosis_site_contact_messages(message_id),
  status TEXT NOT NULL CHECK(status IN ('sending','sent','needs_review')),
  provider_message_id TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  last_error_type TEXT
);
CREATE INDEX IF NOT EXISTS gnosis_admin_manual_emails_by_date ON gnosis_admin_manual_emails(created_at DESC);
