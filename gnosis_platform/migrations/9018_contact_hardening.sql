-- First-party contact protection. No IP addresses or message hashes.
ALTER TABLE gnosis_site_contact_messages ADD COLUMN quarantine_reason TEXT;
CREATE INDEX gnosis_contact_quarantine ON gnosis_site_contact_messages(quarantine_reason,created_at) WHERE deleted_at IS NULL;
CREATE TABLE gnosis_contact_consumed_tokens (
 token_id TEXT PRIMARY KEY, email_digest TEXT NOT NULL, accepted_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL
);
CREATE INDEX gnosis_contact_token_time ON gnosis_contact_consumed_tokens(accepted_ms);
CREATE INDEX gnosis_contact_token_sender ON gnosis_contact_consumed_tokens(email_digest,accepted_ms);
CREATE TABLE gnosis_contact_spam_counters (
 minute INTEGER NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('accepted','quarantined','rejected','rate_limited')),
 n INTEGER NOT NULL, PRIMARY KEY(minute,outcome)
);
CREATE TABLE gnosis_contact_quarantine_releases (
 message_id TEXT PRIMARY KEY REFERENCES gnosis_site_contact_messages(message_id),
 actor_account_id TEXT NOT NULL REFERENCES accounts(account_id), released_at TEXT NOT NULL
);
