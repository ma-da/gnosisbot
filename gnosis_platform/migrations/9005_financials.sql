-- GNOSIS FINANCIALS V1. Sources and financial reporting remain admin-only.
CREATE TABLE gnosis_finance_items (
 item_id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT 'General',
 kind TEXT NOT NULL CHECK(kind IN ('monthly_cost','one_time_cost','revenue','monthly_revenue')),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
 status TEXT NOT NULL CHECK(status IN ('active','planned','incurred','received','disabled')),
 starts_on TEXT,
 ends_on TEXT,
 occurs_on TEXT,
 memo TEXT NOT NULL DEFAULT '',
 deleted_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE gnosis_finance_provider_balances (
 provider_id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 units TEXT NOT NULL DEFAULT 'USD',
 quantity TEXT,
 rate_usd TEXT,
 state TEXT NOT NULL CHECK(state IN ('unknown','reported','unlimited','disabled')),
 source TEXT NOT NULL DEFAULT 'operator',
 observed_at TEXT,
 notes TEXT NOT NULL DEFAULT '',
 deleted_at TEXT,
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE gnosis_finance_stripe (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 gross_cents INTEGER NOT NULL CHECK(gross_cents>=0),
 fees_cents INTEGER NOT NULL CHECK(fees_cents>=0),
 refunds_cents INTEGER NOT NULL CHECK(refunds_cents>=0),
 as_of TEXT NOT NULL,
 source TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE gnosis_finance_settings (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 project_start TEXT NOT NULL,
 solana_address TEXT,
 rstory_mint TEXT,
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE gnosis_finance_audit (
 audit_id TEXT PRIMARY KEY,
 actor TEXT NOT NULL,
 action TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 before_json TEXT,
 after_json TEXT,
 at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO gnosis_finance_settings(singleton,project_start) VALUES(1,'2026-10-01');
INSERT INTO gnosis_finance_items(item_id,name,category,kind,amount_cents,status,starts_on,memo) VALUES
 ('seed-digitalocean','DigitalOcean','Infrastructure','monthly_cost',6000,'active','2026-10-01','Recurring hosting'),
 ('seed-godaddy','GoDaddy','Domains','monthly_cost',2000,'active','2026-10-01','Recurring domain services'),
 ('seed-pinata','Pinata IPFS','Storage','monthly_cost',2500,'active','2026-10-01','Recurring IPFS'),
 ('seed-resend','Resend','Email','monthly_cost',2000,'active','2026-10-01','Recurring mail service');
INSERT INTO gnosis_finance_items(item_id,name,category,kind,amount_cents,status,occurs_on,memo) VALUES
 ('seed-independent-verification','Independent expert verification','Verification','one_time_cost',50000,'planned',NULL,'Science/technical review'),
 ('seed-marketing','Third-party marketing completion','Marketing','one_time_cost',50000,'planned',NULL,'Upcoming marketing tasks'),
 ('seed-attorney','Contract attorney retainer','Legal','one_time_cost',100000,'planned',NULL,'Optional, only if needed');
INSERT INTO gnosis_finance_provider_balances(provider_id,name,units,quantity,rate_usd,state,notes) VALUES
 ('iqm','IQM Resonance','QPU seconds',NULL,'0.30','unknown','Estimated minimum USD/sec published by IQM; confirm backend-specific rate'),
 ('qci','QCI','access',NULL,NULL,'unlimited','Unlimited access presently; zero assigned monetary valuation'),
 ('deepseek','DeepSeek','USD',NULL,'1','unknown','Enter remaining prepaid USD balance if available'),
 ('deepinfra','DeepInfra','USD',NULL,'1','unknown','Enter remaining prepaid USD balance if available'),
 ('ankr','Ankr Web3 API','USD',NULL,'1','unknown','Enter remaining prepaid USD balance if available');
