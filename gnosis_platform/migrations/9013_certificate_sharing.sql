CREATE TABLE certificate_circuit_profiles (
 circuit_sha256 TEXT PRIMARY KEY, circuit_version TEXT NOT NULL, logical_qubits INTEGER NOT NULL CHECK(logical_qubits>0),
 evidence TEXT NOT NULL, approved_at TEXT NOT NULL
);
CREATE TRIGGER certificate_profiles_no_update BEFORE UPDATE ON certificate_circuit_profiles BEGIN SELECT RAISE(ABORT,'Immutable profile'); END;
CREATE TRIGGER certificate_profiles_no_delete BEFORE DELETE ON certificate_circuit_profiles BEGIN SELECT RAISE(ABORT,'Immutable profile'); END;
CREATE TABLE certificate_shares (
 certificate_id TEXT PRIMARY KEY REFERENCES reading_certificates(certificate_id),
 token_hash TEXT NOT NULL UNIQUE, enabled_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE certificate_work_attempts (consultation_id TEXT PRIMARY KEY REFERENCES consultations(consultation_id),last_attempt TEXT NOT NULL);
