# Initial production deployment on Ubuntu

Target: `/opt/gnosis` (private Git checkout), `/opt/gnosis-venv`, `/etc/gnosis/gnosis.env`, `/var/lib/gnosis`. Caddy example below is optional; if an existing reverse proxy is running, merge the site config instead of replacing a live configuration. Commands assume a dedicated Ubuntu 24.04 host with Python 3.12; review package install and DNS changes before executing. The candidate has not been installed on a real server yet.

## 1. Install and verify source

Create a **private** GitHub repo and commit reviewed release source. Scan the staged tree for secrets and check rights first. On the server use a read-only deploy key or other protected Git authentication. Never embed tokens in clone URLs or env in Git. Use the actual repository URL and reviewed tag only. Example:

```sh
sudo apt update
sudo apt install git python3.12 python3.12-venv
sudo useradd --system --home-dir /var/lib/gnosis --shell /usr/sbin/nologin gnosis
sudo install -d -o gnosis -g gnosis -m 0700 /var/lib/gnosis /var/backups/gnosis
sudo install -d -o root -g gnosis -m 0750 /etc/gnosis
# Clone as a trusted operator with correct permissions and credentials.
sudo git clone git@github.com:OWNER/REPO.git /opt/gnosis
cd /opt/gnosis
sudo git checkout v0.10.0-alpha.1
sudo python3.12 -m venv /opt/gnosis-venv
sudo /opt/gnosis-venv/bin/python -m pip install -r requirements.txt
sudo /opt/gnosis-venv/bin/python -m pip check
sudo install -o root -g gnosis -m 0640 .env.example /etc/gnosis/gnosis.env
sudoedit /etc/gnosis/gnosis.env
```

Use root-owned read-only application checkout with no credentials accessible to the service user. Install Node and dev requirements only in a separate testing environment if running the full release suite on-server. Validate pinned wheels in a clean Python 3.12 environment before tagging. Never use `--reload` for prod. Domain and public origin must match the actual site. Add firewall rules for SSH (restricted) and public 80/443 only; loopback 8000 must not be exposed.

## 2. Decide state: new sandbox or migrated production ledger

**Existing Gnosis state:** stop old API/worker and quiesce all stock allocations. Take SQLite backup using `scripts/backup_db.py` and a consistent protected backup of the archive tree, signing key, exact public proof bytes, contact encryption key, provider configuration and other state. Transfer over a trusted encrypted path, restore under `/var/lib/gnosis`, chmod 0600 private keys/files and chown service user. Verify original public-key fingerprint and checkpoint continuity; audit existing stored readings and receipt hashes. Do not initialize a new signing key or import the same stock again. Keep old service disabled for ongoing allocations. Review any saved absolute archive/spool paths on restore; do not rewrite signed reading/provenance bytes. If active IBM jobs or notices exist, inspect/reconcile before starting worker. The ZIP deliberately includes none of this state.

**Genuinely fresh ledger only:** explicitly initialize the database, enforce inventory, initialize signing key, create first signed checkpoint. Do not use these key initialization steps for an existing ledger. Establish independently published pinned public key. Leave Past disabled until approved stock and verified proof are present.

An operator CLI shell (read-only service user, trusted environment; type `exit` when done):

```sh
sudo -u gnosis -H /bin/bash --noprofile --norc
set -a
. /etc/gnosis/gnosis.env
set +a
cd /opt/gnosis
export PYTHONPATH="$PWD"
export PATH="/opt/gnosis-venv/bin:$PATH"
umask 077
python scripts/gnosis_db.py init
# Fresh ledger ONLY, not migrated:
# python scripts/gnosis_transparency.py enforce-inventory
# python scripts/gnosis_transparency.py init-key
# python scripts/gnosis_transparency.py checkpoint
python scripts/gnosis_transparency.py status
python scripts/check_production.py
python scripts/gnosis_provider_audit.py
exit
```

Install OpenTimestamps in separate `/opt/gnosis-ots` virtual environment if needed. Exact OTS version was not in audited Gnosis venv; choose/test it separately and record it. Configure local Bitcoin Core RPC (`core`) or explicitly accept dual-explorer verification (`explorers`) per protocol documentation. Set `GNOSIS_OTS_EXECUTABLE` absolute path. No proof upgrade or submission needed to restore already verified inventory.

## 3. Start API only

```sh
sudo install -m 0644 deploy/gnosis.service /etc/systemd/system/gnosis.service
sudo install -m 0644 deploy/gnosis-worker.service /etc/systemd/system/gnosis-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now gnosis.service
sudo systemctl status gnosis.service --no-pager
curl -fsS http://127.0.0.1:8000/api/v1/health
```

`check_production.py` rejects insecure origin/cookies, unsafe alpha paid/trial flags, wrong state location and migration mismatch, Past without GQTP enforcement, changed checkpoint key and incomplete provider settings. It is a guard, not complete security assurance. Start worker only after checking recovered job/outbox state explicitly; it can retrieve known IBM jobs and send enabled notices. It never uses a paid submission option. Access log disabled for privacy; monitor aggregate errors privately. Install Caddy following controlled package setup or use existing Caddy. Merge `deploy/Caddyfile` site block, ensure DNS and TLS, validate proxy config (`sudo caddy validate --config /etc/caddy/Caddyfile`) then reload Caddy. Do not bypass TLS or cookie protections. Constrain access to the staging site during acceptance (private network or appropriate proxy-level gate). No CDN caching of authenticated, query-deep-linked or admin requests. Site resources outside this app must not be affected.

## 4. Acceptance checklist (no new QPU jobs)

- Clean pinned Python 3.12 and Node 22 test run; all 13 migrations apply to empty database; hash-only and full QPY verification. Test against a **copy** of original state isolated from real providers; compare checkpoint public key and inventory/credit balances, record immutable table digests where needed.
- `python scripts/audit_corpus.py --live https://gnosis.bot` with accounts enabled; inspect assets and both Oracle landing pages without noindex, private `?reading=` variants noindex/no-store, sitemap canonical research HTML, robots. Verify real browser TLS origin and successful owner-auth resonance PUT.
- Test account creation, key save, sign-in, logout/DOM cleanup, owner-only history, sample demo replay, Classic cast, moving-line becoming, independent rune fixtures and recognition chronology. Ensure no new jobs, credits or casts during replay. Use test accounts/isolated data; confirm wrong-owner requests fail. Initial setup does not need live public QCI or NIST calls; deliberate optional provider acceptance later.
- Confirm existing GQTP checkpoints/proofs match original, receipt verification and approved inventory counts, sensitive files not served. Verify operator-only dashboard authorization, logout, restart, backup and restore. Do not consume valuable stock to test without explicit approval; use a synthetic isolated fixture instead.
- Confirm all paid Future/trial/auto flags are off, payment integration unavailable, email disabled unless intentionally configured. Configure edge limits/registration abuse review, CSP review, privacy/terms, rights/secret review and monitoring before public opening.
- Enable worker only when known pending jobs and emails have been reviewed:

```sh
sudo systemctl enable --now gnosis-worker.service
```

Enable QCI/NIST/Past and optional admin/email flags individually after readiness verification; restart services to apply config. Admin access is role checked; prefer private access. Never turn on live paid submission flags with these initial alpha service units. Keep `.env` protected. Future hardware/general release and payment processing are separate milestones.
