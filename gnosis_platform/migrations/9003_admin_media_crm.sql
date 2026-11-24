-- Gnosis media/outreach CRM: administrative, encrypted, separate from credit ledger.
-- Forward-only; applied explicitly with gnosis_platform.db.migrate().
CREATE TABLE IF NOT EXISTS gnosis_media_contacts (
  contact_id TEXT PRIMARY KEY CHECK(length(contact_id) = 32),
  details_ciphertext BLOB NOT NULL,
  status TEXT NOT NULL DEFAULT 'researching' CHECK(status IN
    ('researching','ready','contacted','follow_up','responded','published','declined','archived')),
  next_followup TEXT,
  claim_code_given INTEGER NOT NULL DEFAULT 0 CHECK(claim_code_given IN (0,1)),
  claim_code_given_at TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gnosis_media_contacts_status ON gnosis_media_contacts(status,updated_at);
CREATE INDEX IF NOT EXISTS idx_gnosis_media_contacts_followup ON gnosis_media_contacts(next_followup);
CREATE TABLE IF NOT EXISTS gnosis_media_activity (
  activity_id TEXT PRIMARY KEY CHECK(length(activity_id) = 32),
  contact_id TEXT NOT NULL REFERENCES gnosis_media_contacts(contact_id),
  actor_account_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('created','updated','note','contacted','reply','coverage','follow_up')),
  details_ciphertext BLOB NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gnosis_media_activity_contact ON gnosis_media_activity(contact_id,created_at);
