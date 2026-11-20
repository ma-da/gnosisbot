from .config import get_settings
from .db import connect,migrate
from .registry import catalog
import argparse

def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=('init','status','services'))
    arg=p.parse_args()
    if arg.command=='services':
        for x in catalog(): print(f"{x['service_id']:<27} {x['credits']:>2} credit(s) provider={x['provider']}")
        return
    path=get_settings().db_path
    if arg.command=='status' and not path.exists():
        print('Not initialized:',path)
        return
    with connect(path) as db:
        if arg.command=='init': print('Applied:',migrate(db))
        print('Database:',path)
        print('Tables:',db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
        print('Migration versions:',[r[0] for r in db.execute('SELECT version FROM schema_migrations ORDER BY version')])

if __name__=='__main__': main()
