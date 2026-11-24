-- Admin-only indicative quote snapshots. NOT payments; NOT taxable receipts; NOT credit issuance.
-- Each row belongs to an existing staged quote and is immutable after insert by app code.
CREATE TABLE gnosis_commerce_price_snapshots (
  quote_id TEXT PRIMARY KEY REFERENCES gnosis_commerce_quotes(quote_id),
  asset TEXT NOT NULL CHECK(asset IN ('USD','SOL','RSTORY')),
  usd_face_value TEXT NOT NULL,
  usd_payable_reference TEXT NOT NULL,
  asset_unit_price_usd TEXT NOT NULL,
  asset_amount TEXT NOT NULL,
  discount_bps INTEGER NOT NULL CHECK(discount_bps IN (0,2000)),
  valuation_policy TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  quote_snapshot_json TEXT NOT NULL CHECK(json_valid(quote_snapshot_json)),
  is_payment INTEGER NOT NULL DEFAULT 0 CHECK(is_payment=0)
);
CREATE INDEX gnosis_commerce_price_snapshots_asset_idx
  ON gnosis_commerce_price_snapshots(asset,fetched_at);
