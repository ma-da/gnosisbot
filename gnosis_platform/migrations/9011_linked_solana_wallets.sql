-- Verified, revocable account-owned public wallet addresses only.
-- No wallet secrets, transfers, payment settlement, or credit ledger mutation.
CREATE TABLE gnosis_wallet_links (
  link_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  wallet_address TEXT NOT NULL,
  linked_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE UNIQUE INDEX gnosis_wallet_active_account ON gnosis_wallet_links(account_id) WHERE revoked_at IS NULL;
CREATE UNIQUE INDEX gnosis_wallet_active_address ON gnosis_wallet_links(wallet_address) WHERE revoked_at IS NULL;
CREATE TABLE gnosis_wallet_challenges (
  challenge_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  wallet_address TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT
);
CREATE INDEX gnosis_wallet_challenges_rate ON gnosis_wallet_challenges(account_id,created_at DESC);
