"""Gnosis operator aggregate snapshots. No account IDs, questions, raw readings or secrets."""
import json, math, os, shutil, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .public_inventory import snapshot as inventory_snapshot
from .config import get_settings

def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def number(value):
    if isinstance(value,bool) or value is None: return None
    try: v=float(value)
    except (ValueError,TypeError,OverflowError): return None
    return v if math.isfinite(v) and v>=0 else None

def json_obj(value):
    try: x=json.loads(value or '{}'); return x if isinstance(x,dict) else {}
    except (ValueError,TypeError): return {}

def overhead():
    v=number(os.getenv('GNOSIS_IBM_REQUEST_OVERHEAD_SECONDS','2'))
    if v is None or v>60: raise ValueError('Invalid IBM request overhead')
    return v

def store_snapshot(db,name,payload):
    db.execute('INSERT INTO gnosis_admin_snapshots VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET payload_json=excluded.payload_json,observed_at=excluded.observed_at',(name,json.dumps(payload,allow_nan=False),stamp()))

def get_snapshot(db,name):
    r=db.execute('SELECT payload_json,observed_at FROM gnosis_admin_snapshots WHERE name=?',(name,)).fetchone()
    if not r:return {'status':'not_configured','as_of':None}
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(r['observed_at'].replace('Z','+00:00'))).total_seconds()
    return {**json_obj(r['payload_json']),'as_of':r['observed_at'],'stale':age>86400}

def reading_counts(db,days=30,now=None):
    today=(now or datetime.now(timezone.utc)).date(); start=today-timedelta(days=days-1)
    buckets=[(start+timedelta(days=i)).isoformat() for i in range(days)]
    # Exactly one saved, completed primary reading per consultation; no demos/replay and no shot counts.
    rows=db.execute('''WITH primary_readings AS (
      SELECT c.consultation_id,c.application_id,date(c.finished_at) AS day,
      COALESCE((SELECT s.service_id FROM service_requests s WHERE s.consultation_id=c.consultation_id
        AND s.status='completed' AND s.service_id NOT LIKE '%.ai_enhancement'
        ORDER BY s.started_at,s.request_id LIMIT 1),'unknown') AS service_id
      FROM consultations c JOIN reading_results r USING(consultation_id) WHERE c.status='completed')
      SELECT application_id,service_id,day,count(*) AS n FROM primary_readings GROUP BY application_id,service_id,day''').fetchall()
    series={}; unknown=0
    for r in rows:
        key=(r['application_id'],r['service_id']); item=series.setdefault(key,dict(application_id=key[0],service_id=key[1],total=0,period_total=0,daily=[0]*days))
        item['total']+=r['n']
        if r['day'] is None:unknown+=r['n']
        elif buckets[0]<=r['day']<=buckets[-1]:
            i=(datetime.fromisoformat(r['day']).date()-start).days; item['daily'][i]+=r['n'];item['period_total']+=r['n']
    # Include registered types with zero readings; no public-consent filter for operational totals.
    from .registry import SERVICES
    for sid in SERVICES:
        if sid.endswith('.ai_enhancement'):continue
        app='runes' if sid.startswith('runes.') else 'iching'
        series.setdefault((app,sid),dict(application_id=app,service_id=sid,total=0,period_total=0,daily=[0]*days))
    entries=sorted(series.values(),key=lambda x:x['service_id'])
    return dict(total=sum(x['total'] for x in entries),period_total=sum(x['period_total'] for x in entries),dates=buckets,unknown_date_count=unknown,series=entries)

def job_rows(db):
    jobs={}
    for r in db.execute('''SELECT b.job_id,b.engine,q.metadata_json,e.event_json FROM gqtp_batches b
      LEFT JOIN gqtp_qualifications q USING(batch_id) JOIN gqtp_events e ON e.seq=b.seq'''):
        q=json_obj(r['metadata_json']); counts={x['disposition']:x['n'] for x in db.execute('SELECT disposition,count(*) n FROM gqtp_items WHERE job_id=? GROUP BY disposition',(r['job_id'],))}
        jobs[r['job_id']]=dict(job_id=r['job_id'],engine=r['engine'],kind='inventory',state='acquired',commercial=counts.get('commercial',0),attempted=sum(counts.values()),actual_seconds=number(q.get('qpu_seconds')),resource_units=number(q.get('resource_units')),acquired_at=q.get('acquired_at'),actual_source='IBM final qualification' if number(q.get('qpu_seconds')) is not None else None)
    for r in db.execute('''SELECT j.external_job_id,j.status,j.backend,j.submitted_at,j.finished_at,s.service_id,c.status AS consultation_status
      FROM ibm_future_jobs j JOIN service_requests s USING(request_id) JOIN consultations c USING(consultation_id)
      WHERE j.external_job_id IS NOT NULL'''):
        if r['external_job_id'] in jobs:continue
        engine=r['service_id'].split('.')[1] if r['service_id'].startswith('runes.') else 'iching'
        jobs[r['external_job_id']]=dict(job_id=r['external_job_id'],engine=engine,kind='future',state=r['status'],commercial=1 if r['consultation_status']=='completed' else 0,attempted=None,actual_seconds=None,resource_units=None,acquired_at=r['finished_at'] or r['submitted_at'],actual_source=None)
    usage={r['job_id']:r for r in db.execute('SELECT * FROM gnosis_admin_ibm_usage')}
    timing={r['job_id']:r for r in db.execute('SELECT * FROM gnosis_admin_ibm_timing')}
    extra=overhead()
    for job in jobs.values():
        jid=job['job_id']; u=usage.get(jid); t=timing.get(jid)
        if u is not None: job.update(actual_seconds=u['qpu_seconds'],actual_source=u['source'],actual_as_of=u['observed_at'])
        # Do not conflate IBM billed seconds with measured pre-overhead execution time.
        measured=t['measured_seconds'] if t is not None else None
        baseline=measured if measured is not None else job['actual_seconds']
        job.update(measured_seconds=measured,measured_source=t['source'] if t is not None else None,
                   planning_baseline_seconds=baseline,planning_basis='measured' if measured is not None else ('reported_charge_proxy' if baseline is not None else None),
                   overhead_seconds=extra,estimated_seconds=baseline+extra if baseline is not None else None)
        n=job['commercial'];job.update(actual_per_reading=job['actual_seconds']/n if n and job['actual_seconds'] is not None else None,
                    estimated_per_reading=job['estimated_seconds']/n if n and job['estimated_seconds'] is not None else None,
                    measured_per_reading=measured/n if n and measured is not None else None)
    return sorted(jobs.values(),key=lambda j:(j['acquired_at'] or '',j['job_id']),reverse=True)

def ibm_summary(db):
    rows=job_rows(db)
    def summarize(items):
        # Each job contributes once; per-reading metrics use matching denominators only.
        billed=[j for j in items if j['actual_seconds'] is not None]; estimate=[j for j in items if j['estimated_seconds'] is not None]; measured=[j for j in items if j['measured_seconds'] is not None]
        def total(a,k):return sum(x[k] for x in a) if a else None
        def ratio(a,k):
            den=sum(x['commercial'] for x in a);return sum(x[k] for x in a)/den if den else None
        return dict(requests=len(items),actual_known=len(billed),measured_known=len(measured),estimate_known=len(estimate),commercial=sum(x['commercial'] for x in items),actual_seconds=total(billed,'actual_seconds'),measured_seconds=total(measured,'measured_seconds'),estimated_seconds=total(estimate,'estimated_seconds'),actual_per_reading=ratio(billed,'actual_seconds'),estimated_per_reading=ratio(estimate,'estimated_seconds'),measured_per_reading=ratio(measured,'measured_seconds'))
    return dict(overhead_seconds=overhead(),totals=summarize(rows),inventory=summarize([x for x in rows if x['kind']=='inventory']),future=summarize([x for x in rows if x['kind']=='future']),by_engine=[dict(engine=e,kind=k,**summarize([x for x in rows if x['kind']==k and x['engine']==e])) for e in ('iching','pouch','sticks') for k in ('inventory','future')],jobs=rows[:200],jobs_truncated=len(rows)>200,instance=get_snapshot(db,'ibm_instance'),budget=get_snapshot(db,'ibm_budget'))

def proof_state(db,public_dir):
    rows=[]
    for r in db.execute('SELECT tree_size,envelope_json FROM gqtp_checkpoints ORDER BY tree_size DESC LIMIT 100'):
        n=r['tree_size']; f=public_dir/f'checkpoint-{n}.json'; p=f.with_suffix('.json.ots'); digest=None
        try:
            if f.read_bytes()==r['envelope_json'].encode('ascii') and p.is_file() and 0<p.stat().st_size<=2*1024*1024:digest=hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:pass
        c=db.execute('SELECT * FROM gnosis_admin_btc_checks WHERE tree_size=?',(n,)).fetchone()
        cp_hash=hashlib.sha256(r['envelope_json'].encode('ascii')).hexdigest()
        if c and digest and c['proof_sha256']==digest and c['checkpoint_sha256']==cp_hash:
            status=c['status']; checked=c['checked_at']; heights=json.loads(c['block_heights_json'])
        else: status='proof_saved_not_checked' if digest else 'proof_missing';checked=None;heights=[]
        released=db.execute('SELECT count(*) FROM gqtp_batches WHERE release_checkpoint=?',(n,)).fetchone()[0]
        method=None
        if checked:
            detail=db.execute('SELECT payload_json FROM gnosis_admin_snapshots WHERE name=?',(f'btc_check_{n}',)).fetchone()
            if detail:
                d=json.loads(detail[0])
                if d.get('proof_sha256')==digest and d.get('checkpoint_sha256')==cp_hash and d.get('status')==status:method=d.get('method')
        rows.append(dict(tree_size=n,status=status,checked_at=checked,block_heights=heights,released_batches=released,proof_sha256=digest,checkpoint_sha256=cp_hash,verification_method=method))
    return rows

def overview(db,days=30):
    settings=get_settings(); public=settings.data_dir/'transparency'/'public'
    disk=shutil.disk_usage(settings.data_dir)
    groups=lambda table: {r[0]:r[1] for r in db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status')}
    return dict(schema_version='gnosis.admin.v1',as_of=stamp(),readings=reading_counts(db,days),inventory=inventory_snapshot(db,public),ibm=ibm_summary(db),checkpoints=proof_state(db,public),contacts=get_snapshot(db,'contacts'),stripe={'status':'not_integrated','gross_minor':None,'fees_minor':None,'refunds_minor':None,'net_minor':None},operations=dict(consultations=groups('consultations'),ibm_jobs=groups('ibm_future_jobs'),notifications=groups('gnosis_completion_outbox'),db_bytes=settings.db_path.stat().st_size if settings.db_path.is_file() else None,disk_free_bytes=disk.free,disk_total_bytes=disk.total,unregistered_completed=db.execute("SELECT count(*) FROM consultations c JOIN reading_results r USING(consultation_id) WHERE c.status='completed' AND NOT EXISTS(SELECT 1 FROM gqtp_receipts q WHERE q.consultation_id=c.consultation_id)").fetchone()[0]))
