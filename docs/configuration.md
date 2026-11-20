# Configuration and feature gates

`.env.example` lists application configuration. Copy it outside the repository, never fill it in within Git. The service manager reads it before process start. For CLI use `set -a; . /etc/gnosis/gnosis.env; set +a` as the trusted service user. Do not paste credentials into shell history or logs. Local tests use isolated state and stripped environment. Variables with `1` switches and `YES` switches are intentionally different in the existing application.

| Flag or value | Meaning |
| --- | --- |
| `GNOSIS_DATA_DIR`, `GNOSIS_DB_PATH` | External private state; `/var/lib/gnosis` in production |
| `GNOSIS_WEB_ORIGIN` | Exact Origin for mutation/auth. `https://gnosis.bot` in prod; localhost vs 127.0.0.1 differ |
| `GNOSIS_PUBLIC_BASE_URL` | Email links and public base |
| `GNOSIS_ALLOW_INSECURE_COOKIE` | `1` only for local HTTP development |
| `GNOSIS_ENABLE_ACCOUNTS_API=1` | Attach account, history, service, admin and consultation routes |
| `GNOSIS_ENABLE_RUNES=1` | Rune application service catalog |
| `GNOSIS_ENABLE_RUNE_DEMO=1` | Explicit public synthetic fixture API |
| `GNOSIS_ENABLE_QCI=1`, `QCI_API_TOKEN` | External QCI access, no silent fallback |
| `GNOSIS_ENABLE_NIST=1`, `GNOSIS_ENABLE_RUNE_NIST=1` | Public beacon and separate rune opt-in |
| `GNOSIS_ENABLE_IBM_PAST=1`, `GNOSIS_ENABLE_RUNE_PAST=1` | Only after committed, Bitcoin-verified, approved inventory and state verification |
| `GNOSIS_ENABLE_IBM_ADMIN_TRIAL=YES` | Restricted I Ching trial, off in initial production |
| `GNOSIS_ENABLE_IBM_LIVE_SUBMISSION=YES`, `GNOSIS_ENABLE_IBM_AUTO_SUBMIT=YES` | Paid authorization gates; **off**, plus CLI opt-in required |
| `GNOSIS_ENABLE_IBM_PILOT=YES` | Separate paid pilot authorization; off |
| `GNOSIS_ENABLE_CONSULTATION_SANDBOX=1` | Admin testing only; off |
| `GNOSIS_ENABLE_EMAIL_VERIFICATION=YES` | Verified email enrollment, Resend sender/key and Fernet key required |
| `GNOSIS_ENABLE_COMPLETION_EMAIL=YES` | Worker sends durable authorized notices; off until checked |
| `GNOSIS_ENABLE_TRIAL_EMAIL=YES` | Local admin test recipient only; off |
| `GNOSIS_ENABLE_ADMIN_DASHBOARD=1` | Owner-admin roles checked per request |
| `GNOSIS_PROVISION_ADMIN=YES` | Explicit provisioning CLI gate, not permanent service env |
| `GNOSIS_OTS_EXECUTABLE`, `GNOSIS_BTC_VERIFIER` | Absolute OTS CLI path and `core` or `explorers` |
| `GNOSIS_IBM_INSTANCE`, `GNOSIS_IBM_INSTANCE_LABEL` | Admin metric refresh uses explicit instance; not credential itself |
| `GNOSIS_IBM_REQUEST_OVERHEAD_SECONDS` | Planning overhead, not measured or billed QPU seconds |
| `GNOSIS_FORMSPREE_FORM_ID`, `GNOSIS_FORMSPREE_API_KEY` | Optional contact count audit, not account notification service |
| `GNOSIS_ALERT_*` | Optional SMTP volume alerts, not automatically installed |

IBM SDK credentials must be provisioned separately for the service user using trusted IBM SDK setup, outside the checkout. Worker recovery contacts IBM only for known pending job IDs; no paid flags in the service file. The instance name/CRN and provider credentials never belong in examples. Do not copy developer-wide Qiskit credential files unreviewed. For migrated encrypted contacts reuse the original encryption key from a protected source, not a newly generated key. For a fresh service with no historical contacts, generate only on the target host with `cryptography.fernet.Fernet.generate_key()` and write directly to protected configuration, not shared terminal output.

`python scripts/gnosis_provider_audit.py` reports configuration/stock readiness without calling paid providers. Its optional `--probe-nist` performs one public HTTP request. Health is configuration-derived plus cached public NIST diagnostic; availability is not proof of a verified live quantum cast.
