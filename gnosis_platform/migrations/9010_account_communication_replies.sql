-- Gnosis Communications V0.4.1: add opt-in replies and per-recipient soft hiding.
-- No changes to credits, accounts, identity, payouts, or quantum records.
ALTER TABLE gnosis_account_notices
  ADD COLUMN allow_reply INTEGER NOT NULL DEFAULT 0 CHECK(allow_reply IN (0,1));

CREATE TABLE gnosis_account_notice_replies (
  reply_id TEXT PRIMARY KEY CHECK(length(reply_id)=32),
  notice_id TEXT NOT NULL REFERENCES gnosis_account_notices(notice_id),
  sender_account_id TEXT NOT NULL REFERENCES accounts(account_id),
  recipient_account_id TEXT NOT NULL REFERENCES accounts(account_id),
  client_request_id TEXT NOT NULL CHECK(length(client_request_id)=32),
  body_ciphertext BLOB NOT NULL CHECK(length(body_ciphertext)>0),
  created_at TEXT NOT NULL,
  UNIQUE(sender_account_id,client_request_id)
);
CREATE INDEX gnosis_notice_replies_recipient
  ON gnosis_account_notice_replies(recipient_account_id,created_at DESC,reply_id DESC);
CREATE INDEX gnosis_notice_replies_sender
  ON gnosis_account_notice_replies(sender_account_id,created_at DESC);
CREATE INDEX gnosis_notice_replies_by_notice
  ON gnosis_account_notice_replies(sender_account_id,notice_id,created_at DESC);

CREATE TABLE gnosis_account_message_hides (
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  message_kind TEXT NOT NULL CHECK(message_kind IN ('notice','reply')),
  message_id TEXT NOT NULL CHECK(length(message_id)=32),
  hidden_at TEXT NOT NULL,
  PRIMARY KEY(account_id,message_kind,message_id)
);
