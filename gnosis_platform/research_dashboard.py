"""Public, aggregate-only I Ching research endpoints. No questions/account IDs exposed.

M3D v1 queries reading_facts directly so live results never depend on a stale cache.
Date bounds are UTC days, inclusive start and exclusive end. Masks are bottom-first.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, timedelta
import math
import re
from fastapi import APIRouter, HTTPException, Query
from .db import connect

router = APIRouter(prefix='/api/v1/research', tags=['gnosis-public-research'])
ISO_DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _day(s):
    if s is None: return None
    if not ISO_DAY.fullmatch(s): raise HTTPException(422, 'Expected YYYY-MM-DD UTC date')
    try: return date.fromisoformat(s)
    except ValueError: raise HTTPException(422, 'Invalid UTC date')


def _filters(source, start, end, moving):
    if source is not None and (not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', source)):
        raise HTTPException(422,'Invalid source')
    a,b=_day(start),_day(end)
    if a and b and a >= b: raise HTTPException(422,'End must follow start (exclusive)')
    if moving not in ('all','yes','no'): raise HTTPException(422,'Invalid moving filter')
    clauses=["application_id='iching'"]
    values=[]
    if source: clauses.append('source_id=?');values.append(source)
    if a: clauses.append('completed_at>=?');values.append(a.isoformat()+'T00:00:00')
    if b: clauses.append('completed_at<?');values.append(b.isoformat()+'T00:00:00')
    if moving!='all': clauses.append('moving_count '+('>' if moving=='yes' else '=')+' 0')
    return ' AND '.join(clauses), values


def _gamma_q(a,x):
    """Regularized upper incomplete gamma Q(a,x), using standard convergent forms."""
    if x <= 0: return 1.0
    gl=math.lgamma(a)
    if x < a+1:
        term=1/a; s=term
        for n in range(1,1000):
            term*=x/(a+n);s+=term
            if abs(term)<abs(s)*1e-14: break
        return max(0.0,min(1.0,1-s*math.exp(-x+a*math.log(x)-gl)))
    b=x+1-a;c=1e300;d=1/max(abs(b),1e-300)*(1 if b>=0 else -1);h=d
    for i in range(1,1000):
        an=-i*(i-a);b+=2;d=an*d+b
        if abs(d)<1e-300:d=1e-300
        c=b+an/c
        if abs(c)<1e-300:c=1e-300
        d=1/d;delta=d*c;h*=delta
        if abs(delta-1)<1e-14:break
    return max(0.0,min(1.0,math.exp(-x+a*math.log(x)-gl)*h))


def _stats(counts, total, cells):
    expected=total/cells if cells else 0
    chi=sum((v-expected)**2/expected for v in counts) if expected else None
    # Conventional asymptotic chi-square only when expected count >= 5 per cell.
    p=_gamma_q((cells-1)/2,chi/2) if chi is not None and expected>=5 else None
    return {'expected_per_cell':expected,'chi_square':chi,'degrees_of_freedom':cells-1,
            'p_value':p,'test_applicable':p is not None,
            'note':'Exploratory goodness-of-fit. Assumes independent, identically distributed fair coin casts; not evidence of causation.'}


def distribution_data(db, *, source=None,start=None,end=None,phase='primary',moving='all'):
    if phase not in ('primary','relating'):raise HTTPException(422,'Invalid phase')
    where,args=_filters(source,start,end,moving)
    col='primary_mask' if phase=='primary' else 'relating_mask'
    rows=db.execute(f'SELECT {col} AS mask,COUNT(*) AS n FROM reading_facts WHERE {where} GROUP BY {col}',args)
    counts={int(r['mask']):int(r['n']) for r in rows}
    values=[counts.get(i,0) for i in range(64)];total=sum(values)
    return {'schema_version':'gnosis.observatory.v1','phase':phase,'source':source or 'all',
            'start_utc':start,'end_utc_exclusive':end,'moving':moving,'total_readings':total,
            'hexagrams':[{'mask':i,'count':values[i],'expected':total/64,'ratio':values[i]/(total/64) if total else None} for i in range(64)],
            'goodness_of_fit':_stats(values,total,64)}


def summary_data(db, *, source=None,start=None,end=None,moving='all'):
    where,args=_filters(source,start,end,moving)
    row=db.execute(f'''SELECT COUNT(*) AS n,COALESCE(SUM(moving_count),0) AS moves,
         COALESCE(SUM(CASE WHEN moving_count>0 THEN 1 ELSE 0 END),0) AS changing
         FROM reading_facts WHERE {where}''',args).fetchone()
    n=row['n']
    move_counts=[0]*7
    for r in db.execute(f'SELECT moving_count,COUNT(*) n FROM reading_facts WHERE {where} GROUP BY moving_count',args):
        move_counts[r['moving_count']]=r['n']
    # The three-coin casting implies p(move)=1/4 for each of six lines.
    expected=[n*math.comb(6,k)*(.25**k)*(.75**(6-k)) for k in range(7)]
    chi=sum((a-e)**2/e for a,e in zip(move_counts,expected)) if n else None
    applicable=bool(moving=='all' and n and min(expected)>=5)
    return {'total_readings':n,'readings_with_moving_lines':row['changing'],
            'moving_line_total':row['moves'],'moving_rate':row['moves']/(6*n) if n else None,
            'moving_count_distribution':[{'moving_count':k,'observed':move_counts[k],'expected':expected[k]} for k in range(7)],
            'moving_count_chi_square':chi,'moving_count_p_value':_gamma_q(3,chi/2) if applicable else None,
            'test_applicable':applicable,
            'moving_count_note':'Moving-count goodness-of-fit applies only to unfiltered moving-line data.' if moving!='all' else 'Fair independent three-coin baseline.',
            'sources':[{'id':r['source_id'],'count':r['n']} for r in db.execute(f'SELECT source_id,COUNT(*) n FROM reading_facts WHERE {where} GROUP BY source_id ORDER BY n DESC,source_id',args)]}


def timeseries_data(db, *, source=None,start=None,end=None,phase='primary',moving='all',mask=None,grain='day'):
    if phase not in ('primary','relating'):raise HTTPException(422,'Invalid phase')
    if grain not in ('day','month'):raise HTTPException(422,'Invalid grain')
    if mask is not None and not 0<=mask<=63:raise HTTPException(422,'Invalid mask')
    where,args=_filters(source,start,end,moving)
    period="substr(completed_at,1,10)" if grain=='day' else "substr(completed_at,1,7)"
    col='primary_mask' if phase=='primary' else 'relating_mask'
    rows=db.execute(f'''SELECT {period} period,COUNT(*) total,
       SUM(CASE WHEN {col}=? THEN 1 ELSE 0 END) selected
       FROM reading_facts WHERE {where}
       GROUP BY period ORDER BY period''',[mask if mask is not None else -1,*args])
    return {'grain':grain,'mask':mask,'phase':phase,'points':[
        {'period':r['period'],'total':r['total'],'observed':r['selected'] if mask is not None else r['total'],
         'expected':r['total']/64 if mask is not None else None} for r in rows]}


@router.get('/hexagrams')
def hexagrams(source:str|None=None,start:str|None=None,end:str|None=None,
             phase:str='primary',moving:str='all'):
    with closing(connect()) as db:
        return distribution_data(db,source=source,start=start,end=end,phase=phase,moving=moving)

@router.get('/summary')
def summary(source:str|None=None,start:str|None=None,end:str|None=None,moving:str='all'):
    with closing(connect()) as db:
        return summary_data(db,source=source,start=start,end=end,moving=moving)

@router.get('/timeseries')
def timeseries(source:str|None=None,start:str|None=None,end:str|None=None,phase:str='primary',
               moving:str='all',mask:int|None=None,grain:str='day'):
    with closing(connect()) as db:
        return timeseries_data(db,source=source,start=start,end=end,phase=phase,moving=moving,mask=mask,grain=grain)
