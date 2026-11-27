-- Account notices V1: admin-authored, one-way, private-by-audience announcements.
-- Published text is immutable. Use archive plus a new notice to issue corrections.
CREATE TABLE gnosis_account_notices (
  notice_id TEXT PRIMARY KEY CHECK(length(notice_id)=32),
  title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 4000),
  audience_kind TEXT NOT NULL CHECK(audience_kind IN ('all','group','account')),
  audience_value TEXT NOT NULL DEFAULT '',
  action_label TEXT NOT NULL DEFAULT '',
  action_href TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','archived')),
  created_by TEXT NOT NULL REFERENCES accounts(account_id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  published_at TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
  CHECK((audience_kind='all' AND audience_value='') OR (audience_kind!='all' AND length(audience_value)>0)),
  CHECK((action_label='' AND action_href='') OR (action_label!='' AND action_href!=''))
);
CREATE INDEX gnosis_account_notices_published
 ON gnosis_account_notices(status,published_at DESC,notice_id DESC);
CREATE INDEX gnosis_account_notices_audience
 ON gnosis_account_notices(audience_kind,audience_value,status);
CREATE TABLE gnosis_account_notice_events (
  event_id TEXT PRIMARY KEY CHECK(length(event_id)=32),
  notice_id TEXT NOT NULL REFERENCES gnosis_account_notices(notice_id),
  actor_account_id TEXT NOT NULL REFERENCES accounts(account_id),
  action TEXT NOT NULL CHECK(action IN ('created','edited','published','archived')),
  revision INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX gnosis_account_notice_events_by_notice
 ON gnosis_account_notice_events(notice_id,created_at);
