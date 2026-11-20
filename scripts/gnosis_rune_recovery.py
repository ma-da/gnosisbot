"""Offline operator recovery; never draws entropy or submits IBM work."""
import argparse,json,sys
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect
from gnosis_platform.transactions import _get_request,finish_request
from gnosis_platform.rune_production import run_claimed


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('status','resume-staged','fail-claimed'));p.add_argument('request_id',nargs='?');p.add_argument('--confirm-api-stopped',action='store_true');a=p.parse_args()
    if not get_settings().db_path.is_file():p.error('Existing database required')
    with closing(connect()) as db:
        if a.command=='status':
            print(json.dumps([dict(x) for x in db.execute("""SELECT r.request_id,r.consultation_id,r.service_id,r.status AS request_status,e.status AS execution_status,e.updated_at FROM service_requests r LEFT JOIN rune_executions e ON e.request_id=r.request_id WHERE r.service_id LIKE 'runes.%' AND r.status='pending' ORDER BY r.started_at""")],indent=2));return
        if not a.confirm_api_stopped or not a.request_id:p.error('Stop ALL API/worker processes first; supply request ID and --confirm-api-stopped')
        req=_get_request(db,a.request_id);row=db.execute('SELECT status FROM rune_executions WHERE request_id=?',(a.request_id,)).fetchone()
        if not req or not req['service_id'].startswith('runes.') or req['status']!='pending' or not row:p.error('No pending claimed rune request')
        if a.command=='resume-staged':
            if row['status']!='staged':p.error('Only staged entropy may be resumed')
            # Independently disable the entropy acquisition method even if the
            # claim unexpectedly disappears. No new entropy is ever authorized.
            from unittest.mock import patch
            with patch('gnosis_platform.rune_production.acquire',side_effect=RuntimeError('Recovery cannot acquire entropy')):
                print(json.dumps({'status':run_claimed(db,req),'request_id':a.request_id}))
        elif row['status']=='claimed':
            finish_request(db,a.request_id,success=False);print(json.dumps({'status':'failed','request_id':a.request_id}))
        else:p.error('Fail-claimed only handles ambiguous claims without staged entropy')
if __name__=='__main__':main()
