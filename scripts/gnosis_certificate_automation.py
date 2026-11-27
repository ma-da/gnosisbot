#!/usr/bin/env python3
import argparse,sys,json,sqlite3
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.db import connect
from gnosis_platform.certificate_automation import cycle,review_profile,approve_profile,find_keys

def main():
    a=argparse.ArgumentParser();a.add_argument('command',choices=['find-key','profile-review','approve-profile','once']);a.add_argument('--db',type=Path,required=True);a.add_argument('--data-dir',type=Path,required=True);a.add_argument('--gqtp-key',type=Path);a.add_argument('--job');a.add_argument('--digest');a.add_argument('--limit',type=int,default=20);a.add_argument('--apply',action='store_true');x=a.parse_args()
    if x.db.resolve()!=Path('/var/lib/gnosis/gnosis.sqlite3') or x.data_dir.resolve()!=Path('/var/lib/gnosis') or not x.db.is_file():a.error('explicit production paths required')
    if x.command=='find-key':print(json.dumps(find_keys(x.data_dir),indent=2));return 0
    if x.command in ('approve-profile','once') and not x.apply:a.error('--apply required')
    if x.command=='once' and not x.gqtp_key:a.error('--gqtp-key required')
    if x.command in ('profile-review','approve-profile') and not x.job:a.error('--job required')
    if x.command=='profile-review':
        db=sqlite3.connect(x.db.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    else:db=connect(x.db)
    with closing(db):
        if not db.execute("SELECT 1 FROM schema_migrations WHERE version='9013_certificate_sharing.sql'").fetchone():a.error('migration 9013 required')
        if x.command=='profile-review':out=review_profile(db,x.job,x.data_dir)
        elif x.command=='approve-profile':out=approve_profile(db,x.job,x.digest,x.data_dir)
        else:out=cycle(db,x.data_dir,x.gqtp_key,x.limit)
        print(json.dumps(out,indent=2));return int(isinstance(out,list) and any(r['state']=='blocked' for r in out))
if __name__=='__main__':sys.exit(main())
