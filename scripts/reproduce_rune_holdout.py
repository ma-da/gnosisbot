"""Reproduce the owner's 500-seed RC1 calibration holdout (not a new holdout)."""
from quantum.sticks.recognition import engine as e
from collections import Counter
import time,json
from pathlib import Path
start=time.perf_counter(); inc=Counter(); raw=Counter(); density=Counter(); occ=Counter()
for i in range(4000,4500):
 c=e.synthetic_casting(i); rows=e.detect_calibration(c); state,s=e.select_calibrated(c,rows); shown={n:x for n,x in s.items() if x['representative'] is not None}; inc.update(shown.keys()); raw.update({x['rune'] for x in state if x['status']!='rejected'}); density[len(shown)]+=1
 for n,x in shown.items(): occ[n]+=x['occurrence_count']
 if (i+1)%100==0: print(i+1,time.perf_counter()-start,flush=True)
v=e.APPROVED_PROFILE['validation']; assert dict(density)=={int(k):x for k,x in v['reading_size_distribution'].items()},(density,v['reading_size_distribution'])
for r in v['results']:
 n=r['rune']; assert abs(inc[n]/5-r['presented_pct'])<1e-9; assert abs(raw[n]/5-r['raw_pct'])<1e-9; assert abs(occ[n]/inc[n]-r['occurrences_when_found'])<1e-9
report=dict(status='PASS',validation_seed=4000,castings=500,shown=dict(inc),raw=dict(raw),occurrences=dict(occ),density=dict(density),mean_symbols=sum(inc.values())/500,mean_occurrences=sum(occ.values())/500,elapsed_seconds=time.perf_counter()-start)
print(json.dumps(report,indent=2))
