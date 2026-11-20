-- Durable audit order for atomic credit admission across API workers.
-- Sequence numbers are assigned inside the BEGIN IMMEDIATE authorization transaction.
CREATE TABLE consultation_admissions (
  admission_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL UNIQUE REFERENCES service_requests(request_id),
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  admitted_at TEXT NOT NULL
);
CREATE INDEX idx_consultation_admissions_account ON consultation_admissions(account_id, admission_seq);
