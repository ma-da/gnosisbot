"""Offline statistical diagnostics for circular sticks (64/128-bit shots).
No IBM jobs, recognition, resampling or modifications of measured data.
"""
from __future__ import annotations
import math
import numpy as np
from scipy import stats


def holm(ps):
    """Holm adjusted p-values; valid with dependent tests."""
    p = np.asarray(ps, dtype=float)
    order = np.argsort(p)
    adjusted = np.empty_like(p)
    adjusted[order] = np.minimum(1, np.maximum.accumulate(p[order] * (len(p)-np.arange(len(p)))))
    return adjusted.tolist()


def validate(result):
    from .decoder import decode_casting
    casts = result['castings']
    meta = result['manifest']
    mapping = meta['physical_qubits_by_classical_bit']
    width = len(mapping)
    assert width in (64, 128) and len(set(mapping)) == width
    assert len(casts) == meta['n_castings'] and len(casts) > 0
    assert meta['shots'] == len(casts) * (1152 // width)
    raw = []
    endpoints = []
    for cast in casts:
        rebuilt = decode_casting(cast['raw_bitstrings_msb_first'], version=cast['version'], width=width)
        # JSON turns tuples into lists; compare geometry numerically.
        assert rebuilt['version'] == cast['version']
        for key in ('point_count','slots','visible_sticks','degenerate_slots'):
            assert rebuilt[key] == cast[key]
        assert len(cast['chords']) == 72
        for a,b in zip(rebuilt['chords'],cast['chords']):
            for key in ('sequence','shot_index','slot_index','endpoint_a','endpoint_b','degenerate'):
                assert a[key] == b[key], (key,a,b)
            assert np.allclose(a['p1'], b['p1'], atol=1e-12, rtol=0)
            assert np.allclose(a['p2'], b['p2'], atol=1e-12, rtol=0)
        raw.extend(cast['raw_bitstrings_msb_first'])
        endpoints.append([(c['endpoint_a'],c['endpoint_b']) for c in rebuilt['chords']])
    # Qiskit strings are MSB-first; column 0 is classical bit c0.
    x = np.array([[int(ch) for ch in s[::-1]] for s in raw],dtype=np.int64)
    ep = np.array(endpoints, dtype=np.int64)
    assert x.shape == (meta['shots'],width) and ep.shape == (len(casts),72,2)
    unpacked = (x.reshape(-1,width//8,8) * (1 << np.arange(8))).sum(axis=2).reshape(len(casts),72,2)
    assert np.array_equal(ep,unpacked)
    n,w = x.shape
    tests = []
    def add(name, statistic, p, note=''):
        tests.append(dict(test=name, statistic=float(statistic), p=float(p), note=note))
    if len(casts) < 32:
        raise ValueError("Use at least 32 complete castings for statistical validation")
    # 1: overall bit balance; ideal iid null.
    ones = int(x.sum())
    add('Pooled bit balance', ones/x.size, stats.binomtest(ones,x.size).pvalue)
    # 2: per-wire exact binomial tests; Holm accounts for 128 comparisons.
    counts = x.sum(axis=0)
    wp = [stats.binomtest(int(k),n).pvalue for k in counts]
    wa = holm(wp)
    wires = [dict(bit=i, physical=int(mapping[i]), ones=int(counts[i]), fraction=float(counts[i]/n), p=float(wp[i]), p_holm=float(wa[i])) for i in range(w)]
    add(f'Any biased wire ({w} tests)', max(abs(counts/n-.5)),min(wa))
    # 3: within-shot all-pairs Pearson phi test for binary independence.
    # Degenerate constant columns are already caught by wire balance.
    s = counts.astype(float); centered = x.T @ x - np.outer(s,s)/n
    denom = np.sqrt(np.outer(s*(1-s/n),s*(1-s/n)))
    phi = np.divide(centered,denom,out=np.zeros_like(centered),where=denom>0)
    ii,jj = np.triu_indices(w,1)
    pr = phi[ii,jj]; pp = stats.chi2.sf(n*pr**2,1)
    pa = holm(pp)
    pairs = [dict(bits=[int(i),int(j)],physical=[int(mapping[i]),int(mapping[j])],phi=float(r),p=float(p),p_holm=float(a)) for i,j,r,p,a in zip(ii,jj,pr,pp,pa)]
    add(f'Any within-shot dependence ({w*(w-1)//2} pairs)', max(abs(pr)), min(pa),'Asymptotic Pearson 2x2 tests; does not exclude higher-order dependence.')
    # 4: successive-shot transition rates per wire. XORs are iid fair
    # under the iid fair-bit null even though adjacent pairs overlap.
    changes = np.count_nonzero(x[1:] != x[:-1], axis=0)
    lp = [stats.binomtest(int(k),n-1).pvalue for k in changes]; la = holm(lp)
    lag = [dict(bit=i,physical=int(mapping[i]),transition_fraction=float(changes[i]/(n-1)),p=float(lp[i]),p_holm=float(la[i])) for i in range(w)]
    add(f'Any abnormal lag-1 transition rate ({w} wires)',max(abs(changes/(n-1)-.5)),min(la),'Tests iid fair transitions in returned shot order, not physical timestamps.')
    # 5: endpoint occupancy.
    hist = np.bincount(ep.ravel(),minlength=256)
    t = stats.chisquare(hist)
    add('256-point endpoint uniformity',t.statistic,t.pvalue)
    # 6: shortest circular separation; exact finite-grid law.
    diff = np.abs(ep[:,:,0]-ep[:,:,1]); d = np.minimum(diff,256-diff)
    lengths = 2*np.sin(np.pi*d/256)
    dh = np.bincount(d.ravel(),minlength=129)
    probs=np.full(129,2/256); probs[[0,128]]=1/256
    t=stats.chisquare(dh, d.size*probs)
    add('129-bin chord separation distribution',t.statistic,t.pvalue)
    deg=int(dh[0]); add('Zero-length chord count',deg,stats.binomtest(deg,d.size,1/256).pvalue,'Overlaps with separation test; retained as a useful diagnostic.')
    # 7: interior crossings via alternating distinct endpoints.
    m=72; i,j=np.triu_indices(m,1)
    a,b=ep[:,i,0],ep[:,i,1]; c,e=ep[:,j,0],ep[:,j,1]
    lo=np.minimum(a,b); hi=np.maximum(a,b)
    distinct=(a!=b)&(c!=e)&(a!=c)&(a!=e)&(b!=c)&(b!=e)
    cross=distinct & (((c>lo)&(c<hi)) != ((e>lo)&(e<hi)))
    per_cast=cross.sum(axis=1)
    # Given a chord with directed separation k, its crossing probability
    # with an independent chord is 2(k-1)(N-k-1)/N^2 for k != 0.
    N=256; k=np.arange(N); q=np.zeros(N); q[1:]=2*(k[1:]-1)*(N-k[1:]-1)/N**2
    p=float(q.mean()); cov=float(np.mean(q*q)-p*p)
    mean=math.comb(m,2)*p
    var=math.comb(m,2)*p*(1-p)+6*math.comb(m,3)*cov
    z=(per_cast.mean()-mean)/math.sqrt(var/len(casts))
    add('Mean proper crossings per casting',z,2*stats.norm.sf(abs(z)),'Normal approximation across iid castings; variance includes shared-chord covariance.')
    for row,adj in zip(tests,holm([t['p'] for t in tests])):
        row['p_holm_across_tests']=adj
    report=dict(job_id=result['job_id'], backend=meta['backend'], circuit_sha256=meta['sha256'], shots=n, castings=len(casts), slots=int(d.size), total_bits=int(x.size), integrity='PASS', tests=tests,
        geometry=dict(endpoint_counts=hist.tolist(), separation_counts=dh.tolist(), separation_expected=(d.size*probs).tolist(), degenerate=deg, expected_degenerate=d.size/256, mean_length=float(lengths.mean()), ideal_mean_length=float(np.dot(2*np.sin(np.pi*np.arange(129)/256),probs)), mean_crossings=float(per_cast.mean()), ideal_mean_crossings=mean, ideal_sd_crossings=math.sqrt(var), crossing_z=float(z)),
        wires=sorted(wires,key=lambda r:r['p']), pairs=sorted(pairs,key=lambda r:r['p']), lag=sorted(lag,key=lambda r:r['p']))
    # Conditional runs: account for each wire's measured marginal balance.
    n1 = counts.astype(float); n0 = n-n1
    runs = 1+changes
    mu = 1+2*n0*n1/n
    variance = 2*n0*n1*(2*n0*n1-n)/(n*n*(n-1))
    zrun = np.divide(runs-mu, np.sqrt(np.maximum(variance,0)), out=np.zeros_like(mu), where=variance>0)
    rp = 2*stats.norm.sf(abs(zrun)); ra = holm(rp)
    report['conditional_runs'] = sorted([dict(bit=i, physical=int(mapping[i]), runs=int(runs[i]), expected_runs=float(mu[i]), z=float(zrun[i]), p=float(rp[i]), p_holm=float(ra[i])) for i in range(w) if variance[i]>0], key=lambda r:r['p'])
    report['conditional_runs_significant'] = sum(r['p_holm']<0.05 for r in report['conditional_runs'])
    return report


def print_report(report):
    print('Job:', report['job_id'], '| backend:',report['backend'])
    print('Integrity:',report['integrity'], '| castings:',report['castings'], '| bits:',report['total_bits'])
    print('\nTest                                               statistic       p      Holm p')
    for t in report['tests']:
        print(f"{t['test']:48s} {t['statistic']:10.4g} {t['p']:10.4g} {t['p_holm_across_tests']:10.4g}")
    g=report['geometry']
    print(f"\nDegenerate slots: {g['degenerate']} (ideal {g['expected_degenerate']:.2f})")
    print(f"Mean chord length: {g['mean_length']:.4f} (ideal {g['ideal_mean_length']:.4f}; unit circle)")
    print(f"Mean crossings: {g['mean_crossings']:.2f} (ideal {g['ideal_mean_crossings']:.2f})")
    print('Largest wire imbalances:')
    for r in report['wires'][:5]: print(r)
    print('Largest pair associations:')
    for r in report['pairs'][:5]: print(r)
    print('Smallest adjusted p:',min(t['p_holm_across_tests'] for t in report['tests']))
    print('Conditional runs significant:', report['conditional_runs_significant'])
    print('Non-significance does not establish independence or certify randomness.')
