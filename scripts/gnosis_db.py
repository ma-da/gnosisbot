"""Run from gnosis repository root: python scripts/gnosis_db.py init|status|services"""
import argparse
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect, migrate
from gnosis_platform.registry import catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "status", "services"))
    args = parser.parse_args()
    if args.command == "services":
        for service in catalog():
            print(f"{service['service_id']:<27} {service['credits']:>2} credit(s) provider={service['provider']}")
        return
    settings = get_settings()
    if args.command == "status" and not settings.db_path.exists():
        print("Database not initialized:", settings.db_path)
        return
    with connect() as db:
        versions = migrate(db) if args.command == "init" else []
        tables = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        migrations = db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() if tables else []
    print("Database:", settings.db_path)
    print("Tables:", tables)
    print("Migrations:", [r[0] for r in migrations])
    if versions: print("Applied:", versions)

if __name__ == "__main__":
    main()
