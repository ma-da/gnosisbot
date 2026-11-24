-- Gnosis Contacts V3: local privacy deletion and reversible Resend inbox visibility.
-- No Resend provider email is deleted by this migration or its API.
ALTER TABLE gnosis_site_contact_messages ADD COLUMN deleted_at TEXT;
CREATE INDEX gnosis_site_contact_visible
 ON gnosis_site_contact_messages(deleted_at,archived_at,read_at,created_at DESC);
CREATE TABLE gnosis_admin_site_contact_deletions (
  message_id TEXT PRIMARY KEY REFERENCES gnosis_site_contact_messages(message_id),
  actor_account_id TEXT NOT NULL REFERENCES accounts(account_id),
  deleted_at TEXT NOT NULL
);
CREATE TABLE gnosis_admin_received_mail_hidden (
  provider_email_id TEXT PRIMARY KEY,
  hidden_at TEXT NOT NULL,
  actor_account_id TEXT NOT NULL REFERENCES accounts(account_id)
);
CREATE TABLE gnosis_admin_received_mail_audit (
  audit_id TEXT PRIMARY KEY,
  provider_email_id TEXT NOT NULL,
  actor_account_id TEXT NOT NULL REFERENCES accounts(account_id),
  action TEXT NOT NULL CHECK(action IN ('hide','restore')),
  created_at TEXT NOT NULL
);
CREATE INDEX gnosis_admin_received_mail_audit_by_email
 ON gnosis_admin_received_mail_audit(provider_email_id,created_at DESC);
