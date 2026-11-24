-- Watch-only observations. Never a payment, invoice, settlement or credit ledger.
CREATE TABLE gnosis_solana_watch_state (
  network TEXT NOT NULL,
  wallet TEXT NOT NULL,
  target_address TEXT NOT NULL,
  asset TEXT NOT NULL CHECK(asset IN ('SOL','RSTORY')),
  started_at TEXT NOT NULL,
  newest_signature TEXT,
  last_scanned_at TEXT,
  last_error TEXT,
  PRIMARY KEY(network, wallet, target_address)
);
CREATE TABLE gnosis_solana_watch_observations (
  network TEXT NOT NULL,
  wallet TEXT NOT NULL,
  signature TEXT NOT NULL,
  asset TEXT NOT NULL CHECK(asset IN ('SOL','RSTORY')),
  destination_account TEXT NOT NULL,
  block_slot INTEGER NOT NULL,
  block_time INTEGER NOT NULL,
  delta_base_units TEXT NOT NULL,
  amount_display TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'observed_unmatched' CHECK(status='observed_unmatched'),
  detected_at TEXT NOT NULL,
  PRIMARY KEY(network,wallet,signature,asset,destination_account)
);
CREATE INDEX gnosis_watch_by_time ON gnosis_solana_watch_observations(network,wallet,block_time DESC);
CREATE TABLE gnosis_solana_watch_snapshots (
  network TEXT NOT NULL,
  wallet TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  sol_lamports TEXT NOT NULL,
  rstory_base_units TEXT NOT NULL,
  token_account_count INTEGER NOT NULL,
  PRIMARY KEY(network,wallet,observed_at)
);
