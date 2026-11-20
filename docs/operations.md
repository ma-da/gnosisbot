# Operations

Operate from the repo root with the service-user environment loaded. Keep a single active writable ledger and worker. Use protected logs and do not expose saved results or credentials when seeking support.

| Command | Action |
| --- | --- |
| `python scripts/gnosis_db.py init` | Explicit forward migration; stop service and back up first |
| `python scripts/gnosis_db.py status` | Schema summary |
| `python scripts/check_production.py` | Safe setup guard, no provider calls |
| `python scripts/gnosis_provider_audit.py` | Configuration/stock readiness, optional public NIST diagnostic |
| `python scripts/gnosis_event_worker.py status` | Pending/recovery state summary |
| `python scripts/gnosis_inventory.py status` | Qualified archive inventory metrics |
| `python scripts/gnosis_transparency.py status` | GQTP state, signing/checkpoint/commitment counts |
| `python scripts/gnosis_admin_metrics.py overview --days 30` | Admin operational metrics |
| `python -m gnosis_platform.provision --help` | Explicit credit/invitation/admin operation |
| `python -m gnosis_platform.research_export --help` | Private research export/backfill |
| `python scripts/audit_corpus.py --live http://127.0.0.1:8000` | Public catalog, demo, headers, no hardware |
| `python scripts/verify_quantum.py` | Pure offline scientific verification |
| `python scripts/backup_db.py --out /var/backups/gnosis/UNIQUE.sqlite3` | SQLite backup API plus integrity check; destination must be writable by service user |

## Backups and restore

Stop both API and worker for an operational handoff (prevent receipt/stock changes). SQLite backup is consistent even with WAL, but a complete state backup also includes exact GQTP signing key (0600), public signed log/checkpoints/proof bytes, private IBM source and staged result archives, rune private audit storage and encryption secret in external protected configuration. Keep the entire archive set consistent with the database. The database backup utility does not copy the keys or archive tree. Encrypt backups, restrict permissions, verify integrity and test restore in an isolated directory without providers or a live worker. Avoid raw copy of a live SQLite file with uncheckpointed WAL. Restore the existing public key identity, not a fresh root. Do not run two instances with copied stock.

For updates, snapshot state and record current Git commit, stop services, checkout the reviewed next tag, update the venv based on pins, migrate explicitly, run startup guard and acceptance tests, restart. Forward-only migrations mean rollback to old code alone is not safe if schema changed; restore the consistent pre-update state only if no new allocations/receipts would be lost. For live production reconcile writes first, plan forward remediation.

## Monitoring

Inspect systemd service status and restricted journals; disk capacity is important for raw IBM archives. `scripts/gnosis_volume_monitor.py --help` handles thresholds and optional SMTP alerts; no timer installed. Admin metrics distinguish final billed QPU charge seconds, measured time and proxy/planning overhead; don't add them together or claim proxy is measured. Formspree API metric refresh is optional and never stores message bodies. `GNOSIS_ENABLE_ADMIN_DASHBOARD=1` additionally requires an admin-authenticated session. Operator `refresh-ibm --instance ...` retrieves known jobs only; no new submissions. OTS upgrade/check is operator managed; no background timer configured here. See transparency docs.

If any network call has uncertain outcome: do not repeat paid submissions or consume substitute readings. Recover by known ID or reconcile the durable claim manually. No payment processor or automatic credit sales are enabled by the alpha templates.
