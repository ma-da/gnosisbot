"""Read-only Solana monitor CLI. Run under the dedicated systemd service."""
import argparse
import json
import sys
from contextlib import closing
from .db import connect
from .solana_watch import AnkrRpc,WatchError,configuration,scan,status

def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--once',action='store_true')
    g.add_argument('--status',action='store_true')
    args=p.parse_args()
    with closing(connect()) as db:
        if args.status:
            print(json.dumps(status(db),sort_keys=True))
            return
        net,_,_,key=configuration(db)
        print(json.dumps(scan(db,AnkrRpc(key,net)),sort_keys=True))

if __name__=='__main__':
    try:main()
    except (WatchError,ValueError) as ex:
        # All WatchError messages are authored to exclude API keys and remote URLs.
        print('WATCH ERROR:',str(ex),file=sys.stderr)
        raise SystemExit(1)
