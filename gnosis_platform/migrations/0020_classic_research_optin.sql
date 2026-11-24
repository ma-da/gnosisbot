-- Anonymous Classic I Ching: explicit consent-only, restricted research intake.
-- No public query routes. No account, IP, credential, cookie or personal ID stored.
-- The client-reported line values are NOT independently verified physical data.
CREATE TABLE classic_research_optins (
  submission_id TEXT PRIMARY KEY,
  submission_key TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  question TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
  inquiry_style TEXT NOT NULL CHECK (inquiry_style IN ('direct', 'meditative')),
  line_values_json TEXT NOT NULL,
  research_publication_consent INTEGER NOT NULL CHECK (research_publication_consent = 1),
  source TEXT NOT NULL CHECK (source = 'browser_crypto'),
  verification_status TEXT NOT NULL CHECK (verification_status = 'self_reported_client_cast'),
  classification TEXT NOT NULL CHECK (classification = 'restricted_review_required')
);
CREATE INDEX idx_classic_research_optins_created ON classic_research_optins(created_utc);
