"""SQLite initialization and forward-only, transactional SQL migrations."""
import sqlite3
from pathlib import Path
from importlib.resources import files
from .config import get_settings


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path else get_settings().db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(target), timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=15000")
    return db


def migrate(db: sqlite3.Connection) -> list[str]:
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
    applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
    installed = []
    migration_dir = files("gnosis_platform").joinpath("migrations")
    for resource in sorted(migration_dir.iterdir(), key=lambda x: x.name):
        if not resource.name.endswith(".sql") or resource.name in applied:
            continue
        sql = resource.read_text(encoding="utf-8")
        # executescript issues implicit COMMIT; each migration uses its own explicit transaction.
        script = (
            "BEGIN IMMEDIATE;\n" + sql + "\n"
            + "INSERT INTO schema_migrations(version) VALUES ('" + resource.name + "');\n"
            + "COMMIT;"
        )
        db.executescript(script)
        installed.append(resource.name)
    return installed
