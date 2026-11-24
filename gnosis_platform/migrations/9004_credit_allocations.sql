-- Issued promotional credits remain active until transferred into an account.
-- No historic ledger writes; existing invitations remain legacy mint-on-redemption.
CREATE TABLE gnosis_credit_allocations (
 allocation_id TEXT PRIMARY KEY,
 invitation_id TEXT NOT NULL UNIQUE REFERENCES invitations(invitation_id),
 campaign_group TEXT NOT NULL CHECK(campaign_group IN ('Alpha Test','Media','Promo')),
 batch_id TEXT NOT NULL,
 amount INTEGER NOT NULL CHECK(amount > 0),
 created_at TEXT NOT NULL,
 redeemed_at TEXT,
 redeemed_by TEXT REFERENCES accounts(account_id),
 created_by TEXT NOT NULL REFERENCES accounts(account_id),
 CHECK ((redeemed_at IS NULL) = (redeemed_by IS NULL))
);
CREATE INDEX gnosis_credit_allocations_batch_idx ON gnosis_credit_allocations(batch_id);
CREATE INDEX gnosis_credit_allocations_group_idx ON gnosis_credit_allocations(campaign_group, redeemed_at);
CREATE TABLE gnosis_credit_batches (
 batch_id TEXT PRIMARY KEY,
 idempotency_key TEXT NOT NULL UNIQUE,
 campaign_group TEXT NOT NULL CHECK(campaign_group IN ('Alpha Test','Media','Promo')),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 100),
 credits_each INTEGER NOT NULL CHECK(credits_each BETWEEN 1 AND 100000),
 expires_days INTEGER NOT NULL CHECK(expires_days BETWEEN 1 AND 365),
 created_by TEXT NOT NULL REFERENCES accounts(account_id),
 created_at TEXT NOT NULL
);
