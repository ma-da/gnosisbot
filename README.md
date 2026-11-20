# Gnosis.bot

**Research software alpha · I Ching and Elder Futhark · candidate v0.10.0-alpha.1**

Gnosis is a browser-based oracle and research observatory that compares traditional casting methods, cryptographic randomness, external quantum entropy and actual quantum-processor measurements. Its visualizations replay recorded outcomes; they are not observations of wavefunctions or evidence of divinatory efficacy.

The I Ching engine uses six groups of three coin qubits and six coherently computed moving flags. The Elder Futhark experiments use a 15-qubit strict rank sampler and a screened 64-active-qubit circular geometry sampler. Classical interpretation is separate from entropy, hardware records and authenticated transactions.

## Quick start (Ubuntu / WSL, Python 3.12)

Use the pinned environment from the working project; Node 22+ is only needed for frontend tests. No frontend build, provider token, account database or hardware job is required for public demos. Do not use a real state directory for tests.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip check
python scripts/test_release.py

# Local isolated application state (outside the checkout).
export PYTHONPATH="$PWD"
export GNOSIS_DATA_DIR="$HOME/.gnosis-alpha-test"
export GNOSIS_ENABLE_ACCOUNTS_API=1
export GNOSIS_ENABLE_RUNES=1
export GNOSIS_ENABLE_RUNE_DEMO=1
export GNOSIS_WEB_ORIGIN=http://localhost:8000
export GNOSIS_ALLOW_INSECURE_COOKIE=1 # localhost ONLY
python scripts/gnosis_db.py init
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000/`, `/quantum-oracle.html`, `/rune-oracle.html`, `/account.html` and `/research.html`. Account keys are generated in the browser. Local Classic I Ching is not stored on the server; server-backed readings require authentication. No new paid hardware jobs are enabled by these commands. The front end loads D3 and fonts from third-party CDNs; complete offline browser rendering is not guaranteed.

## Repository

| Path | Responsibility |
| --- | --- |
| `app/` | FastAPI entry, public routes, presentation, website, approved public data |
| `gnosis_platform/` | Accounts, credit/consultation state, providers, private history, transparency, research, admin |
| `quantum/` | Logical circuits, exact retained QPY files, deterministic decoders, validation and recognition |
| `scripts/` | Operational utilities, offline tests, corpus updates and archival imports |
| `tests/` | Python and Node regression suite |
| `docs/` | Design and operations documentation |
| `deploy/` | Systemd and HTTPS reverse-proxy templates |

## Quantum engines

- [I Ching: coherent moving-line computation](quantum/iching/README.md)
- [Rune Pouch: strict ordered sampling without replacement](quantum/pouch/README.md)
- [Circular Sticks: geometry and measurement packing](quantum/sticks/README.md)
- [RC1 rune recognition: frozen geometric analysis](quantum/sticks/recognition/README.md)
- [Evidence and verification boundaries](quantum/README.md)

## Documentation

[Architecture](docs/architecture.md) · [Deployment](docs/deployment.md) · [Configuration](docs/configuration.md) · [Accounts](docs/accounts.md) · [Operations](docs/operations.md) · [Corpus](docs/corpus.md) · [Transparency](docs/quantum-transparency.md) · [Research](docs/research.md) · [Security](SECURITY.md) · [Licensing review](LICENSING.md) · [Release notes](CHANGELOG.md) · [Validation report](docs/release-validation.md)

The current I Ching corpus is v0.9.0 / schema 2.0.0, AI-assisted, human revision onging. All saved physical observations and cryptographic receipts retain their original interpretation-independent identity. Production corpus updates use `scripts/update_corpus.py`; do not modify measurement data to change interpretations.

