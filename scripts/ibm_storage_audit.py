#!/usr/bin/env python3
"""Read-only capacity report. Does not print submitted questions or credentials."""
from pathlib import Path
from statistics import mean
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect
from gnosis_platform.ibm_worker import capacity_scenarios
from contextlib import closing
import json


def main():
    with closing(connect()) as db:
        db_file=db.execute('PRAGMA database_list').fetchall()[0][2]
        count=db.execute('SELECT COUNT(*) FROM reading_results').fetchone()[0]
        ibm=db.execute("SELECT COUNT(*) FROM reading_results WHERE json_extract(provenance_json,'$.provider')='ibm'").fetchone()[0]
        qci=db.execute("SELECT COUNT(*) FROM reading_results WHERE json_extract(provenance_json,'$.provider')='qci'").fetchone()[0]
        lengths=db.execute("""SELECT LENGTH(r.reading_json)+LENGTH(r.provenance_json) AS bytes
           FROM reading_results r WHERE json_extract(r.provenance_json,'$.provider')='ibm'""").fetchall()
        avg=round(mean([r[0] for r in lengths])) if lengths else None
    p=Path(db_file)
    free=shutil.disk_usage(p.parent).free
    path=get_settings().data_dir/'ibm-results-restricted'
    spool_count=0; spool_bytes=0
    if path.is_dir():
        for item in path.glob('*.json'):
            spool_count+=1;spool_bytes+=item.stat().st_size
    print(json.dumps({
        'database_file_bytes':p.stat().st_size,
        'database_wal_bytes':Path(str(p)+'-wal').stat().st_size if Path(str(p)+'-wal').exists() else 0,
        'database_shm_bytes':Path(str(p)+'-shm').stat().st_size if Path(str(p)+'-shm').exists() else 0,
        'disk_free_bytes':free,'total_readings':count,'ibm_readings':ibm,'qci_readings':qci,
        'avg_ibm_result_and_provenance_bytes':avg,
        'spool_files':spool_count,'spool_file_bytes':spool_bytes,
        'planning_scenarios_50kb':capacity_scenarios(),
    },indent=2))

if __name__=='__main__':main()
