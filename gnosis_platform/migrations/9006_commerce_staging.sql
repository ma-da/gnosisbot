-- Staging preview ONLY: zero payment processing, zero issuer/ledger mutations.
-- Deliberately separate from payment_orders / payment_events.
CREATE TABLE gnosis_commerce_quotes (
 quote_id TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES accounts(account_id),
 offer_id TEXT NOT NULL,
 method TEXT NOT NULL CHECK(method IN ('stripe','solana','rstory')),
 credits INTEGER NOT NULL CHECK(credits>0),
 total_display TEXT NOT NULL,
 fees_display TEXT NOT NULL,
 payment_detail TEXT NOT NULL,
 refund_summary TEXT NOT NULL,
 terms_version TEXT NOT NULL,
 disclosure_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('quoted','superseded','previewed'))
);
CREATE INDEX gnosis_commerce_quotes_account_idx ON gnosis_commerce_quotes(account_id,created_at);
CREATE TABLE gnosis_commerce_previews (
 preview_id TEXT PRIMARY KEY,
 quote_id TEXT NOT NULL UNIQUE REFERENCES gnosis_commerce_quotes(quote_id),
 account_id TEXT NOT NULL REFERENCES accounts(account_id),
 idempotency_key TEXT NOT NULL UNIQUE,
 terms_version TEXT NOT NULL,
 disclosure_hash TEXT NOT NULL,
 accepted_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status='simulation_only')
);
CREATE INDEX gnosis_commerce_previews_account_idx ON gnosis_commerce_previews(account_id,accepted_at);
