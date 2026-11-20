"""Restricted local JSONL export. NOT an automatic public publication pipeline."""
import argparse
import hashlib
import json
import os
import sqlite3
from uuid import uuid4
from datetime import datetime,timezone
from pathlib import Path
from .db import connect


def export_jsonl(db, destination:Path, *, start=None, end=None):
    """Export ALL completed readings, including questions. Local restricted data only.

    destination must be a new path; never overwrite existing archives.
    Inclusive start / exclusive end in ISO UTC (YYYY-MM-DD works for daily bounds).
    """
    destination=Path(destination)
    if destination.exists() or destination.with_suffix(destination.suffix+'.manifest.json').exists():
        raise FileExistsError('Archive files already exist')
    destination.parent.mkdir(parents=True,exist_ok=True)
    conditions=["c.status='completed'"]
    args=[]
    if start: conditions.append('c.finished_at >= ?');args.append(start)
    if end: conditions.append('c.finished_at < ?');args.append(end)
    where=' AND '.join(conditions)
    rows=db.execute(f'''SELECT c.consultation_id,c.account_id,c.question,c.inquiry_style,
      c.created_at,c.finished_at,c.research_publication_consent,
      sr.service_id,sr.provider,r.schema_version,r.reading_json,r.provenance_json,
      m.raw_payload_json,m.measurement_status,
      f.resonated AS reading_resonated,f.first_marked_at AS resonance_first_marked_at,
      f.updated_at AS resonance_updated_at
      FROM consultations c JOIN reading_results r ON r.consultation_id=c.consultation_id
      JOIN service_requests sr ON sr.consultation_id=c.consultation_id
      LEFT JOIN reading_measurements m ON m.consultation_id=c.consultation_id
      LEFT JOIN reading_resonance f ON f.consultation_id=c.consultation_id
      WHERE {where} ORDER BY c.finished_at,c.consultation_id''',args)
    temp=destination.with_name(destination.name+'.partial')
    if temp.exists(): raise FileExistsError('Partial export already exists')
    count=0
    digest=hashlib.sha256()
    try:
        with open(temp,'xb') as stream:
            os.chmod(temp,0o600)
            for row in rows:
                item=dict(row)
                for key in ('reading_json','provenance_json','raw_payload_json'):
                    item[key.removesuffix('_json')]=json.loads(item.pop(key)) if item[key] is not None else None
                encoded=(json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
                digest.update(encoded)
                stream.write(encoded)
                count+=1
            stream.flush();os.fsync(stream.fileno())
        temp.rename(destination)
        manifest={'schema_version':'gnosis.research.export.v2','classification':'RESTRICTED_NOT_PUBLIC',
                  'period_start':start,'period_end':end,'record_count':count,
                  'sha256':digest.hexdigest(),'generated_utc':datetime.now(timezone.utc).isoformat(),
                  'filename':destination.name,
                  'warning':'Contains user-submitted questions and account IDs; review and deidentify before public release.'}
        manifest_path=destination.with_suffix(destination.suffix+'.manifest.json')
        with open(manifest_path,'x',encoding='utf-8') as out:
            json.dump(manifest,out,indent=2)
        os.chmod(manifest_path,0o600)
        # Index the verified-on-write export in SQLite. The export remains a
        # restricted local file; registration does not publish it.
        db.execute('''INSERT INTO research_archives
          (archive_batch_id,period_start,period_end,schema_version,record_count,
           storage_uri,manifest_sha256,created_at,verification_status)
          VALUES(?,?,?,?,?,?,?,?,?)''',
          (uuid4().hex,start or '',end or '',manifest['schema_version'],count,
           str(destination.resolve()),hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
           manifest['generated_utc'],'written_unverified'))
        db.commit()
        return manifest
    finally:
        if temp.exists(): temp.unlink()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=('backfill','export'))
    p.add_argument('--output',type=Path)
    p.add_argument('--start')
    p.add_argument('--end')
    args=p.parse_args()
    with connect() as db:
        if args.command=='backfill':
            from .research import backfill
            print('Research records created:',backfill(db))
        else:
            if not args.output: p.error('export requires --output')
            print(json.dumps(export_jsonl(db,args.output,start=args.start,end=args.end),indent=2))
if __name__=='__main__':main()
