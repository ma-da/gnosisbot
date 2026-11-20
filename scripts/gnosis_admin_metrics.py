#!/usr/bin/env python3
"""Refresh operator metadata only. Never submits IBM jobs or accesses reading contents."""
import argparse,base64,json,os,re,sys
from pathlib import Path
from contextlib import closing
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.db import connect
from gnosis_platform.admin_metrics import number,stamp,store_snapshot,job_rows,overview

def refresh_ibm(db,instance,limit):
    from qiskit_ibm_runtime import QiskitRuntimeService
    # Explicit instance avoids reporting remaining funding on an unrelated instance.
    service=QiskitRuntimeService(instance=instance)
    u=service.usage()
    fields=('usage_consumed_seconds','usage_limit_seconds','usage_allocation_seconds','usage_remaining_seconds','usage_consumed_ru','usage_limit_ru','usage_allocation_ru','usage_remaining_ru')
    data={k:number(u.get(k)) for k in fields}
    if data['usage_consumed_seconds'] is None and data['usage_consumed_ru'] is None:raise ValueError('No recognized instance usage fields')
    data.update(status='reported',source='IBM Runtime active instance usage')
    def text_field(x):return str(x)[:160] if isinstance(x,str) else None
    data['plan']=text_field(u.get('plan_id'));data['instance_label']=text_field(os.getenv('GNOSIS_IBM_INSTANCE_LABEL','Configured instance'))
    # Dollar budget is deliberately separate from provider runtime allocation.
    store_snapshot(db,'ibm_instance',data)
    # Use all known Gnosis jobs (not other experiments), prioritizing missing final usage.
    jobs=sorted(job_rows(db),key=lambda j:j['actual_seconds'] is not None)[:limit]
    report={'instance':data,'jobs_checked':0,'final_usage_records':0,'unavailable_jobs':0}
    for row in jobs:
        report['jobs_checked']+=1
        try:
            m=service.job(row['job_id']).metrics();usage=m.get('usage') or {}
            v=number(usage.get('qpu_charge_time_seconds'))
            if usage.get('status')!='complete' or v is None:raise ValueError('Final charge time unavailable')
            db.execute('INSERT INTO gnosis_admin_ibm_usage VALUES(?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET qpu_seconds=excluded.qpu_seconds,observed_at=excluded.observed_at,source=excluded.source',(row['job_id'],v,stamp(),'ibm_runtime_final_usage'))
            report['final_usage_records']+=1
        except Exception:report['unavailable_jobs']+=1
    return report

def refresh_contacts(db):
    fid=os.environ.get('GNOSIS_FORMSPREE_FORM_ID',''); key=os.environ.get('GNOSIS_FORMSPREE_API_KEY','')
    if not re.fullmatch('[A-Za-z0-9]{4,64}',fid) or not key: raise ValueError('Configure Formspree form ID and API key')
    auth=base64.b64encode((':'+key).encode()).decode();count=0;size=100;seen=set()
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=build_opener(NoRedirect())
    # Count accepted non-spam submissions; pagination is bounded and fails closed.
    for _ in range(1000):
        offset=count
        req=Request('https://formspree.io/api/0/forms/'+fid+'/submissions?'+urlencode({'limit':size,'offset':offset,'order':'asc','spam':'false'}),headers={'Authorization':'Basic '+auth,'Accept':'application/json','User-Agent':'GnosisAdmin/1.0'})
        with opener.open(req,timeout=20) as f: raw=f.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('Oversized Formspree page')
        page=json.loads(raw).get('submissions')
        if not isinstance(page,list) or len(page)>size or any(not isinstance(x,dict) for x in page):raise ValueError('Unexpected Formspree response')
        # Guard against a server ignoring the offset. Persist no form contents.
        import hashlib
        digest=hashlib.sha256(json.dumps(page,sort_keys=True).encode()).digest()
        if page and digest in seen:raise ValueError('Repeated Formspree page')
        seen.add(digest);count+=len(page)
        if not page:
            data={'status':'reported','count':count,'scope':'Available non-spam submissions for configured form','source':'Formspree submissions API'};store_snapshot(db,'contacts',data);return data
    raise ValueError('Formspree scan limit reached; no snapshot updated')

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('refresh-ibm');a.add_argument('--instance',default=os.getenv('GNOSIS_IBM_INSTANCE'));a.add_argument('--max-jobs',type=int,default=30)
    sub.add_parser('refresh-contacts')
    a=sub.add_parser('contact-count');a.add_argument('count',type=int);a.add_argument('--scope',required=True)
    a=sub.add_parser('measured-time');a.add_argument('job_id');a.add_argument('seconds',type=float);a.add_argument('--source',required=True)
    a=sub.add_parser('overview');a.add_argument('--days',type=int,default=30)
    a=sub.add_parser('budget-usd');a.add_argument('--limit',type=float,required=True);a.add_argument('--spent',type=float,required=True)
    a=p.parse_args()
    try:
        with closing(connect()) as db:
            if a.cmd=='refresh-ibm':
                if not a.instance or a.instance=='auto' or not 1<=a.max_jobs<=200:raise ValueError('Explicit IBM instance and max-jobs 1–200 required')
                result=refresh_ibm(db,a.instance,a.max_jobs)
            elif a.cmd=='refresh-contacts':result=refresh_contacts(db)
            elif a.cmd=='contact-count':
                if a.count<0 or not a.scope.strip():raise ValueError('Nonnegative count and scope required')
                result={'status':'reported','count':a.count,'scope':a.scope[:200],'source':'Operator Formspree snapshot'};store_snapshot(db,'contacts',result)
            elif a.cmd=='budget-usd':
                if number(a.limit) is None or number(a.spent) is None:raise ValueError('Nonnegative USD amounts required')
                result={'status':'reported','limit_usd':a.limit,'spent_usd':a.spent,'remaining_usd':max(0,a.limit-a.spent),'source':'Operator IBM billing console snapshot'};store_snapshot(db,'ibm_budget',result)
            elif a.cmd=='measured-time':
                if a.job_id not in {j['job_id'] for j in job_rows(db)} or number(a.seconds) is None or not a.source.strip():raise ValueError('Known job, nonnegative measured seconds and source required')
                db.execute('INSERT INTO gnosis_admin_ibm_timing VALUES(?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET measured_seconds=excluded.measured_seconds,observed_at=excluded.observed_at,source=excluded.source',(a.job_id,a.seconds,stamp(),a.source[:200]));result={'recorded':True}
            else:
                if not 1<=a.days<=365:raise ValueError('Days must be 1–365')
                result=overview(db,a.days)
        print(json.dumps(result,indent=2,allow_nan=False))
    except Exception as e:
        # Avoid logging credentials or external response bodies; diagnose locally if needed.
        p.exit(1,'Admin metrics command failed: '+type(e).__name__+' (check arguments, credentials and provider access)\n')
if __name__=='__main__':main()
