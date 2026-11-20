# Extracted from the supplied notebook. See SOURCE_MAP.md.


# Notebook cell 1 (zero-based)

"""Deterministic rune spotting prototype for the 256-point circular casting.

No Qiskit, network, random sampling or interpretation in recognition. Synthetic
fixtures and Monte Carlo use a separate, explicitly classical random generator.
Coordinates are Cartesian, y upward; lengths are in unit-circle radii.
"""

from dataclasses import dataclass

from functools import lru_cache

from itertools import combinations

from math import sin, cos, tau, pi, atan2, hypot, degrees, acos

import random

N = 256

POINTS = tuple((cos(tau*i/N), sin(tau*i/N)) for i in range(N))

EPS = 1e-9

def sub(a,b): return (a[0]-b[0],a[1]-b[1])

def add(a,b): return (a[0]+b[0],a[1]+b[1])

def mul(a,s): return (a[0]*s,a[1]*s)

def norm(a): return hypot(*a)

def cross(a,b): return a[0]*b[1]-a[1]*b[0]

def dot(a,b): return a[0]*b[0]+a[1]*b[1]

def mid(a,b): return mul(add(a,b),.5)

def dist(a,b): return norm(sub(a,b))

def axis_angle(v): return degrees(atan2(v[1],v[0]))%180

def angle_diff(a,b): return abs((a-b+90)%180-90)

@dataclass(frozen=True)
class Geometry:
    a: int; b: int; p: tuple; q: tuple; v: tuple; length: float; angle: float
    midpoint: tuple; center_distance: float

@lru_cache(maxsize=32640)
def geometry(a,b):
    if not 0 <= a < b < N: raise ValueError('Expected canonical distinct endpoints')
    p,q=POINTS[a],POINTS[b]; v=sub(q,p); m=mid(p,q)
    return Geometry(a,b,p,q,v,norm(v),axis_angle(v),m,norm(m))

def build_library():
    return {(a,b):geometry(a,b) for a,b in combinations(range(N),2)}

@dataclass(frozen=True)
class Stick:
    seq: int; a: int; b: int
    @property
    def p(self): return POINTS[self.a]
    @property
    def q(self): return POINTS[self.b]
    @property
    def v(self): return sub(self.q,self.p)
    @property
    def geom(self): return geometry(*sorted((self.a,self.b)))
    def at(self,t): return add(self.p,mul(self.v,t))

def casting_sticks(casting):
    """Validate indices and sequence; collapse exact duplicates for recognition only."""
    rows=casting['chords'] if isinstance(casting,dict) else casting
    if len(rows)>72: raise ValueError('Max 72 slots')
    seen=set(); sticks=[]
    for i,r in enumerate(rows,1):
        a,b=r['endpoint_a'],r['endpoint_b']
        if r['sequence']!=i or type(a) is not int or type(b) is not int or not (0<=a<N and 0<=b<N):
            raise ValueError('Invalid sequence or endpoint')
        key=tuple(sorted((a,b)))
        if a==b or key in seen: continue
        seen.add(key); sticks.append(Stick(i,a,b))
    return sticks

def intersection(a,b):
    d=cross(a.v,b.v)
    if abs(d)<EPS: return None
    w=sub(b.p,a.p); t=cross(w,b.v)/d; u=cross(w,a.v)/d
    if not (-EPS<=t<=1+EPS and -EPS<=u<=1+EPS): return None
    t=max(0.,min(1.,t)); u=max(0.,min(1.,u))
    return a.at(t),t,u

DEFAULT_RULES = dict(isa_angle=4., isa_length=1.65,
    gebo_angle=15., gebo_min_arm=.26, gebo_center_fraction=.30, gebo_diagonal_min=25.,
    dagaz_vertical=12., dagaz_parallel=12., dagaz_min_width=.22,
    dagaz_min_height=.30, dagaz_ratio_min=.45, dagaz_ratio_max=1.20,
    dagaz_level=.20, dagaz_symmetry=.25,
    ingwaz_parallel=8., ingwaz_axis=12., ingwaz_min_width=.45,
    ingwaz_ratio_min=1.10, ingwaz_ratio_max=2.0,
    ingwaz_side_ratio=1.25, ingwaz_midpoint=.12, ingwaz_orthogonal=10.)

GLYPHS={'Isa':'ᛁ','Gebo':'ᚷ','Dagaz':'ᛞ','Ingwaz':'ᛜ'}

def segment(s,t,u):
    lo,hi=sorted((float(t),float(u)))
    if not -EPS<=lo<hi<=1+EPS: raise ValueError('Invalid highlight interval')
    return dict(stick=s.seq,t_start=max(0.,lo),t_end=min(1.,hi))

def score(errors):
    # Not a probability: 1 for ideal; geometric fit penalties within allowed limits.
    return 1-.5*sum(min(1.,max(0.,e))**2 for e in errors)/len(errors)

def candidate(name,segs,quality,*,first=None,embedded=False):
    ids=sorted(s['stick'] for s in segs)
    return dict(id=name+':'+','.join(map(str,ids)),rune=name,glyph=GLYPHS[name],
        first_appearance=max(ids) if first is None else first,score=quality,
        segments=segs,embedded_only=embedded,children=[],components=[])

class Recognition:
    def __init__(self,casting,rules=None):
        self.rules={**DEFAULT_RULES,**(rules or {})}
        self.sticks=casting_sticks(casting)
        self.by_id={s.seq:s for s in self.sticks}
        self.intersections={}
        for a,b in combinations(self.sticks,2):
            hit=intersection(a,b)
            if hit is not None:
                self.intersections[a.seq,b.seq]=hit
                self.intersections[b.seq,a.seq]=(hit[0],hit[2],hit[1])
        self.candidates={}
    def hit(self,a,b): return self.intersections.get((a.seq,b.seq))
    def put(self,c):
        old=self.candidates.get(c['id'])
        if old is None or (old['embedded_only'] and (not c['embedded_only'] or c['first_appearance']<old['first_appearance'])):
            self.candidates[c['id']]=c
        return c['id']
    def isa(self):
        r=self.rules
        for s in self.sticks:
            g=s.geom; d=angle_diff(g.angle,90)
            if d<=r['isa_angle']+EPS and g.length>=r['isa_length']:
                self.put(candidate('Isa',[segment(s,0,1)],score([d/r['isa_angle'],(2-g.length)/(2-r['isa_length'])])))
    def gebo(self):
        r=self.rules
        for a,b in combinations(self.sticks,2):
            hit=self.hit(a,b)
            if hit is None: continue
            _,t,u=hit
            # Require an interior, reasonably central crossing. Symmetric
            # trimmed arms end at a deterministic distance supported by both lines.
            if (a.geom.angle<90)==(b.geom.angle<90): continue
            if any(min(angle_diff(s.geom.angle,0),angle_diff(s.geom.angle,90))<r['gebo_diagonal_min'] for s in (a,b)): continue
            err=abs(90-angle_diff(a.geom.angle,b.geom.angle))
            if err>r['gebo_angle'] or min(t,1-t,u,1-u)<r['gebo_center_fraction']: continue
            arm=min(t*a.geom.length,(1-t)*a.geom.length,u*b.geom.length,(1-u)*b.geom.length)
            if arm<r['gebo_min_arm']: continue
            sa=arm/a.geom.length; sb=arm/b.geom.length
            self.put(candidate('Gebo',[segment(a,t-sa,t+sa),segment(b,u-sb,u+sb)],
                score([err/r['gebo_angle'],abs(t-.5)/(.5-r['gebo_center_fraction']),abs(u-.5)/(.5-r['gebo_center_fraction'])])))
    def dagaz(self):
        r=self.rules
        stems=[s for s in self.sticks if angle_diff(s.geom.angle,90)<=r['dagaz_vertical']]
        for a,b in combinations(stems,2):
            parallel=angle_diff(a.geom.angle,b.geom.angle)
            if parallel>r['dagaz_parallel']: continue
            # Only diagonals intersecting both stems, with opposite slopes.
            eligible=[s for s in self.sticks if s not in (a,b) and 15<=angle_diff(s.geom.angle,90)<=78 and self.hit(a,s) and self.hit(b,s)]
            for c,d in combinations(eligible,2):
                if (c.geom.angle<90)==(d.geom.angle<90): continue
                ac,ad,bc,bd=self.hit(a,c),self.hit(a,d),self.hit(b,c),self.hit(b,d)
                x=self.hit(c,d)
                if x is None: continue
                # Opposite ordering along the two stems in Cartesian y.
                if (ac[0][1]-ad[0][1])*(bc[0][1]-bd[0][1])>=0: continue
                if not (min(ac[2],bc[2])+EPS<x[1]<max(ac[2],bc[2])-EPS and min(ad[2],bd[2])+EPS<x[2]<max(ad[2],bd[2])-EPS): continue
                la,lb=sorted((ac[0],ad[0]),key=lambda p:p[1]); ra,rb=sorted((bc[0],bd[0]),key=lambda p:p[1])
                ca,cb=mid(la,lb),mid(ra,rb)
                w=abs(ca[0]-cb[0]); ha=dist(la,lb); hb=dist(ra,rb); h=(ha+hb)/2
                if w<r['dagaz_min_width'] or h<r['dagaz_min_height']: continue
                ratio=w/h
                if not r['dagaz_ratio_min']<=ratio<=r['dagaz_ratio_max']: continue
                level=max(abs(la[1]-ra[1]),abs(lb[1]-rb[1]))/h
                symmetry=max(abs(ha-hb)/h,dist(x[0],mid(ca,cb))/min(w,h))
                if level>r['dagaz_level'] or symmetry>r['dagaz_symmetry']: continue
                segs=[segment(a,ac[1],ad[1]),segment(b,bc[1],bd[1]),segment(c,ac[2],bc[2]),segment(d,ad[2],bd[2])]
                parent=candidate('Dagaz',segs,score([parallel/r['dagaz_parallel'],level/r['dagaz_level'],symmetry/r['dagaz_symmetry']]))
                # The X is intrinsic to Dagaz, even if it wouldn't pass the
                # standalone Gebo rules. Do not invent an earlier independent event.
                child=candidate('Gebo',segs[2:],parent['score'],first=parent['first_appearance'],embedded=True)
                parent['children']=[self.put(child)]
                parent['components']=[dict(rune='Gebo',id=child['id'],segments=segs[2:])]
                # A full-length independent Isa is suppressed only if its own
                # highlight is almost entirely covered by the parent stem.
                for stem,seg in zip((a,b),segs[:2]):
                    iid='Isa:'+str(stem.seq)
                    if iid in self.candidates and seg['t_end']-seg['t_start']>=.90:
                        parent['children'].append(iid)
                        parent['components'].append(dict(rune='Isa',id=iid,segments=[seg]))
                self.put(parent)
    def ingwaz(self):
        r=self.rules
        up=[s for s in self.sticks if 15<=s.geom.angle<=75]
        down=[s for s in self.sticks if 105<=s.geom.angle<=165]
        def pairs(group):
            return [(a,b) for a,b in combinations(group,2) if angle_diff(a.geom.angle,b.geom.angle)<=r['ingwaz_parallel']]
        pp,qq=pairs(up),pairs(down)
        for a,b in pp:
            for c,d in qq:
                ac,ad,bc,bd=self.hit(a,c),self.hit(a,d),self.hit(b,c),self.hit(b,d)
                if not all((ac,ad,bc,bd)): continue
                # Cycle a-c-b-d. Opposite diagonal midpoint and angle tests.
                v=[ac[0],bc[0],bd[0],ad[0]]
                edges=[sub(v[(i+1)%4],v[i]) for i in range(4)]
                turns=[cross(edges[i],edges[(i+1)%4]) for i in range(4)]
                if not (all(t>EPS for t in turns) or all(t<-EPS for t in turns)): continue
                lens=[norm(e) for e in edges]
                if min(lens)<EPS or max(lens)/min(lens)>r['ingwaz_side_ratio']: continue
                d1,d2=sub(v[2],v[0]),sub(v[3],v[1]); l1,l2=norm(d1),norm(d2)
                w,h=max(l1,l2),min(l1,l2)
                if h<EPS or w<r['ingwaz_min_width'] or not r['ingwaz_ratio_min']<=w/h<=r['ingwaz_ratio_max']: continue
                axis=angle_diff(axis_angle(d1 if l1>=l2 else d2),0)
                orth=abs(90-angle_diff(axis_angle(d1),axis_angle(d2)))
                center=dist(mid(v[0],v[2]),mid(v[1],v[3]))/h
                if axis>r['ingwaz_axis'] or orth>r['ingwaz_orthogonal'] or center>r['ingwaz_midpoint']: continue
                segs=[segment(a,ac[1],ad[1]),segment(b,bc[1],bd[1]),segment(c,ac[2],bc[2]),segment(d,ad[2],bd[2])]
                self.put(candidate('Ingwaz',segs,score([axis/r['ingwaz_axis'],orth/r['ingwaz_orthogonal'],center/r['ingwaz_midpoint'],(max(lens)/min(lens)-1)/(r['ingwaz_side_ratio']-1)])))
    def detect(self):
        self.isa(); self.gebo(); self.dagaz(); self.ingwaz()
        return sorted(self.candidates.values(),key=lambda c:(c['first_appearance'],c['rune'],c['id']))

def recognize(casting,rules=None): return Recognition(casting,rules).detect()

def presentation(candidates,step=72):
    """Reconstruct prefix state; parent suppression applies only after its emergence."""
    active=[c for c in candidates if c['first_appearance']<=step]
    hidden={child for c in active for child in c['children']}
    return [dict(c,status=('embedded' if c['id'] in hidden or c['embedded_only'] else 'independent')) for c in active]

def highlight_segments(casting,candidate):
    sticks={s.seq:s for s in casting_sticks(casting)}
    return [(sticks[s['stick']].at(s['t_start']),sticks[s['stick']].at(s['t_end'])) for s in candidate['segments']]

def synthetic_casting(seed,n=72):
    """Ideal classical model, never a quantum reading."""
    rng=random.Random(seed)
    return from_pairs([(rng.randrange(N),rng.randrange(N)) for _ in range(n)])

def from_pairs(pairs):
    return {'chords':[dict(sequence=i,endpoint_a=a,endpoint_b=b) for i,(a,b) in enumerate(pairs,1)]}

def line_chord(a,b):
    """Fixture-only: extend a line to the circle and quantize its endpoints."""
    v=sub(b,a); aa=dot(v,v); bb=2*dot(a,v); cc=dot(a,a)-1
    root=(bb*bb-4*aa*cc)**.5
    out=[]
    for t in ((-bb-root)/(2*aa),(-bb+root)/(2*aa)):
        p=add(a,mul(v,t)); out.append(round(atan2(p[1],p[0])*N/tau)%N)
    return tuple(out)

def fixtures():
    # Cross first; two vertical sides arrive later. Near-square fixture.
    a=(-.34,-.38); b=(-.34,.38); c=(.34,-.38); d=(.34,.38)
    dagaz=from_pairs([line_chord(a,d),line_chord(b,c),line_chord(a,b),line_chord(c,d)])
    v=[(-.44,0),(0,.29),(.44,0),(0,-.29)]
    diamond=from_pairs([line_chord(v[i],v[(i+1)%4]) for i in range(4)])
    return dagaz,diamond

RULES = dict(opening_min=65., opening_max=115., axis_tolerance=15.,
             primitive_min_arm=.12, kenaz_arm=.30,
             jera_min_dx=.25, jera_max_dx=.85,
             jera_offset_min=.25, jera_offset_max=.70,
             jera_mirror_tolerance=20., jera_gap=.025)

@dataclass(frozen=True)
class Chevron:
    sticks: tuple
    vertex: tuple
    t: tuple
    signs: tuple
    rays: tuple
    available: tuple
    opening: float
    axis: float
    direction: int  # +1 = opens right, -1 = opens left

def chevrons(sticks, rules=None, graph=None):
    """Build reusable oriented chevrons from real pair intersections.

    No independent Kenaz length rule is imposed here: composites can use a
    different scale. Both arms must have enough support on the actual chords.
    """
    r = {**RULES, **(rules or {})}
    out = []
    for a,b in combinations(sticks,2):
        hit=graph.hit(a,b) if graph is not None else intersection(a,b)
        if hit is None: continue
        p,t,u=hit
        for sa in (-1,1):
            for sb in (-1,1):
                da=(t if sa==-1 else 1-t)*a.geom.length
                db=(u if sb==-1 else 1-u)*b.geom.length
                if min(da,db)<r['primitive_min_arm']: continue
                va=mul(a.v,sa/a.geom.length); vb=mul(b.v,sb/b.geom.length)
                opening=degrees(acos(max(-1.,min(1.,dot(va,vb)))))
                if not r['opening_min']<=opening<=r['opening_max']: continue
                bis=add(va,vb); axis=axis_angle(bis)
                if angle_diff(axis,0)>r['axis_tolerance']: continue
                out.append(Chevron((a,b),p,(t,u),(sa,sb),(va,vb),(da,db),opening,axis,1 if bis[0]>0 else -1))
    return out

def intervals(c, arm):
    """Select symmetric actual chord subsegments of a deterministic length."""
    assert 0 < arm <= min(c.available)+EPS
    out=[]
    for s,t,sign in zip(c.sticks,c.t,c.signs):
        end=t+sign*arm/s.geom.length
        lo,hi=sorted((t,end))
        out.append(dict(stick=s.seq,t_start=max(0.,lo),t_end=min(1.,hi)))
    return out

def _point_segment_distance(p,a,b):
    v=sub(b,a); t=max(0.,min(1.,dot(sub(p,a),v)/dot(v,v)))
    return dist(p,add(a,mul(v,t)))

def _segment_gap(a,b,c,d):
    v,w=sub(b,a),sub(d,c); den=cross(v,w)
    if abs(den)>EPS:
        t=cross(sub(c,a),w)/den; u=cross(sub(c,a),v)/den
        if -EPS<=t<=1+EPS and -EPS<=u<=1+EPS: return 0.
    return min(_point_segment_distance(a,c,d),_point_segment_distance(b,c,d),
               _point_segment_distance(c,a,b),_point_segment_distance(d,a,b))

def _candidate(name, segs, quality, components=()):
    # Direction/interval geometry enters IDs to distinguish different rays.
    key=';'.join(f"{s['stick']}:{s['t_start']:.8f}:{s['t_end']:.8f}" for s in sorted(segs,key=lambda x:x['stick']))
    return dict(id=name+':'+key,rune=name,glyph={'Kenaz':'ᚲ','Jera':'ᛃ'}[name],
                first_appearance=max(s['stick'] for s in segs),score=quality,
                segments=segs,components=list(components))

def recognize_kenaz_jera(casting, rules=None, graph=None):
    """Reference composition-based search, no model, no quantum calls."""
    r={**RULES, **(rules or {})}; sticks=graph.sticks if graph is not None else casting_sticks(casting)
    prim=chevrons(sticks,r,graph); found=[]
    # Standalone Kenaz is right opening in this chosen variant.
    for c in prim:
        if c.direction==1 and min(c.available)>=r['kenaz_arm']:
            fit=abs(c.opening-90)/25+angle_diff(c.axis,0)/r['axis_tolerance']
            found.append(_candidate('Kenaz',intervals(c,r['kenaz_arm']),1-.25*fit))
    right=[c for c in prim if c.direction==1]; left=[c for c in prim if c.direction==-1]
    for a in right:
        for b in left:
            dx=b.vertex[0]-a.vertex[0]; dy=a.vertex[1]-b.vertex[1]
            if not r['jera_min_dx']<=dx<=r['jera_max_dx']: continue
            ratio=dy/dx
            if not r['jera_offset_min']<=ratio<=r['jera_offset_max']: continue
            if len({s.seq for s in a.sticks+b.sticks})!=4: continue
            # A 180-degree rotated chevron should have matching ray directions.
            aa=sorted(a.rays,key=lambda v:v[1]); bb=sorted(b.rays,key=lambda v:-v[1])
            mirror=max(degrees(acos(max(-1.,min(1.,-dot(x,y))))) for x,y in zip(aa,bb))
            if mirror>r['jera_mirror_tolerance']: continue
            # Derive common arm length from vertex separation using the chosen
            # template: horizontal arm projection is dx/2 at 45 degrees.
            arm=dx/2**.5
            if min(*a.available,*b.available)<arm: continue
            pa=[add(a.vertex,mul(v,arm)) for v in a.rays]
            pb=[add(b.vertex,mul(v,arm)) for v in b.rays]
            gap=min(_segment_gap(a.vertex,x,b.vertex,y) for x in pa for y in pb)
            if gap<r['jera_gap']: continue
            sa,sb=intervals(a,arm),intervals(b,arm)
            fit=(abs(a.opening-90)/25+abs(b.opening-90)/25+mirror/r['jera_mirror_tolerance']+abs(ratio-.5)/.25)/4
            found.append(_candidate('Jera',sa+sb,1-.5*fit,[dict(rune='Kenaz',segments=sa),dict(rune='Kenaz',segments=sb)]))
    return sorted({c['id']:c for c in found}.values(),key=lambda c:(c['first_appearance'],c['id']))

def contained(child,parent,coverage=.95):
    """Require matching chord IDs AND interval coverage, not bounding boxes."""
    if len({s['stick'] for s in child['segments']})>=len({s['stick'] for s in parent['segments']}): return False
    for s in child['segments']:
        overlap=max((max(0.,min(s['t_end'],p['t_end'])-max(s['t_start'],p['t_start'])) for p in parent['segments'] if p['stick']==s['stick']),default=0.)
        if overlap+EPS < coverage*(s['t_end']-s['t_start']): return False
    return True

def presentation(candidates,step=72):
    active=[c for c in candidates if c['first_appearance']<=step]
    return [dict(c,status='embedded' if c['rune']=='Kenaz' and any(p['rune']=='Jera' and contained(c,p) for p in active) else 'independent') for c in active]

def jera_fixture():
    # Scale/translate normalized template into circle, extend each line to
    # boundary and quantize exactly as a real casting would be recorded.
    a=(-.30,.15); b=(.30,-.15)
    return from_pairs([line_chord(a,(0,.45)),line_chord(a,(0,-.15)),line_chord(b,(0,.15)),line_chord(b,(0,-.45))])

def render(casting,candidate=None,step=72,ax=None):
    import matplotlib.pyplot as plt
    if ax is None: _,ax=plt.subplots(figsize=(5,5))
    ax.add_patch(plt.Circle((0,0),1,fill=False,color='#AAA'))
    ss={s.seq:s for s in casting_sticks(casting) if s.seq<=step}
    for s in ss.values(): ax.plot([s.p[0],s.q[0]],[s.p[1],s.q[1]],color='#a58a6a',alpha=.45,lw=1)
    if candidate is not None and candidate['first_appearance']<=step:
        for seg in candidate['segments']:
            s=ss[seg['stick']]; p,q=s.at(seg['t_start']),s.at(seg['t_end'])
            ax.plot([p[0],q[0]],[p[1],q[1]],color='#008e83',lw=3,solid_capstyle='round')
    ax.set(xlim=(-1.06,1.06),ylim=(-1.06,1.06),aspect='equal'); ax.axis('off')
    return ax

FAMILY_RULES = dict(stem_angle=8., branch_angle=10., branch_parallel=8.,
                    min_gap=.19, max_gap=.38, laguz_stem=.80, laguz_arm=.34,
                    nauthiz_stem=.90, nauthiz_halfbar=.30,
                    sowilo_angle=10., sowilo_min_middle=.28, sowilo_max_middle=.78)

NEW_GLYPHS = {'Fehu':'ᚠ','Ansuz':'ᚨ','Laguz':'ᛚ','Nauthiz':'ᚾ','Sowilo':'ᛊ'}

@dataclass(frozen=True)
class Branch:
    stem: Stick
    arm: Stick
    vertex: tuple
    stem_t: float
    arm_t: float
    sign: int
    available: float
    slope: float

def signed_segment(s,t,delta):
    """delta is physical length along the recorded endpoint ordering."""
    u=t+delta/s.geom.length
    if not -EPS<=u<=1+EPS or abs(u-t)<=EPS: return None
    return segment(s,t,u)

def vertical_segment(s,t,down,up):
    direction=1 if s.v[1]>0 else -1
    a=t-direction*down/s.geom.length
    b=t+direction*up/s.geom.length
    if min(a,b)<-EPS or max(a,b)>1+EPS: return None
    return segment(s,a,b)

def make_new(name,segs,errors,components=()):
    key=';'.join(f"{s['stick']}:{s['t_start']:.8f}:{s['t_end']:.8f}" for s in sorted(segs,key=lambda x:x['stick']))
    return dict(id=name+':'+key,rune=name,glyph=NEW_GLYPHS[name],
                first_appearance=max(s['stick'] for s in segs),score=score(errors),
                segments=segs,components=list(components))

class PrimitiveGraph(Recognition):
    """One intersection cache shared by all 11 recognizers."""
    def __init__(self,casting,geometry_rules=None,family_rules=None):
        super().__init__(casting,geometry_rules)
        self.family={**FAMILY_RULES,**(family_rules or {})}
        self.stems=tuple(s for s in self.sticks if angle_diff(s.geom.angle,90)<=self.family['stem_angle'])
        self.branches={s.seq:[] for s in self.stems}
        for stem in self.stems:
            for arm in self.sticks:
                if arm.seq==stem.seq: continue
                hit=self.hit(stem,arm)
                if hit is None or abs(arm.v[0])<EPS: continue
                p,t,u=hit
                sign=1 if arm.v[0]>0 else -1
                v=mul(arm.v,sign)
                slope=degrees(atan2(v[1],v[0]))
                available=(1-u if sign==1 else u)*arm.geom.length
                if available>EPS:
                    self.branches[stem.seq].append(Branch(stem,arm,p,t,u,sign,available,slope))

    def stem_family(self):
        r=self.family; out=[]
        slope_target=degrees(atan2(.5,.65))
        for stem in self.stems:
            arms=self.branches[stem.seq]
            for b in arms:
                # Laguz: top junction of stem, right/down arm.
                err=abs(b.slope+degrees(atan2(.55,.65)))
                if err<=r['branch_angle']:
                    st=vertical_segment(stem,b.stem_t,r['laguz_stem'],0)
                    ar=signed_segment(b.arm,b.arm_t,b.sign*r['laguz_arm'])
                    if st and ar:
                        out.append(make_new('Laguz',[st,ar],[err/r['branch_angle']]))
                # Nauthiz: central crossbar, right side descends.
                err=abs(b.slope+degrees(atan2(.35,.6)))
                if err<=r['branch_angle']:
                    st=vertical_segment(stem,b.stem_t,r['nauthiz_stem']/2,r['nauthiz_stem']/2)
                    d=r['nauthiz_halfbar']/b.arm.geom.length
                    if st and b.arm_t-d>=-EPS and b.arm_t+d<=1+EPS:
                        ar=segment(b.arm,b.arm_t-d,b.arm_t+d)
                        out.append(make_new('Nauthiz',[st,ar],[err/r['branch_angle']]))
            # Two branches on one stem, independently prefiltered by slope.
            for name,sgn in [('Fehu',1),('Ansuz',-1)]:
                options=[b for b in arms if abs(b.slope-sgn*slope_target)<=r['branch_angle']]
                for a,b in combinations(options,2):
                    low,high=sorted((a,b),key=lambda q:q.vertex[1])
                    gap=dist(low.vertex,high.vertex)
                    parallel=abs(low.slope-high.slope)
                    if not r['min_gap']<=gap<=r['max_gap'] or parallel>r['branch_parallel']: continue
                    # Lengths specified by the approved vector template, scaled by
                    # actual intersection-to-intersection separation along stem.
                    down=(3.30 if name=='Fehu' else 4.0)*gap
                    up=(.70 if name=='Fehu' else 0.)*gap
                    length=hypot(.65,.5)/.5*gap
                    st=vertical_segment(stem,high.stem_t,down,up)
                    lo=signed_segment(low.arm,low.arm_t,low.sign*length)
                    hi=signed_segment(high.arm,high.arm_t,high.sign*length)
                    if st and lo and hi:
                        comps=[dict(rune='Laguz',segments=[st,hi])] if name=='Ansuz' else []
                        out.append(make_new(name,[st,lo,hi],[parallel/r['branch_parallel'],abs(low.slope-sgn*slope_target)/r['branch_angle'],abs(high.slope-sgn*slope_target)/r['branch_angle']],comps))
        return out

    def sowilo(self):
        r=self.family; out=[]; target=degrees(atan2(.5,1))
        rising=[s for s in self.sticks if angle_diff(s.geom.angle,target)<=r['sowilo_angle']]
        falling=[s for s in self.sticks if angle_diff(s.geom.angle,180-target)<=r['sowilo_angle']]
        for middle in falling:
            hits=[(s,self.hit(middle,s)) for s in rising]
            hits=[(s,h) for s,h in hits if h is not None]
            for (a,ha),(b,hb) in combinations(hits,2):
                if ha[0][1]<hb[0][1]: a,b,ha,hb=b,a,hb,ha
                upper,lower=ha[0],hb[0]
                if upper[0]>=lower[0]: continue
                length=dist(upper,lower)
                if not r['sowilo_min_middle']<=length<=r['sowilo_max_middle']: continue
                # Upper ray points up/right; lower ray points down/left.
                sa=1 if a.v[0]>0 else -1
                sb=-1 if b.v[0]>0 else 1
                aa=signed_segment(a,ha[2],sa*length)
                bb=signed_segment(b,hb[2],sb*length)
                if not aa or not bb: continue
                end1=a.at(ha[2]+sa*length/a.geom.length)
                end2=b.at(hb[2]+sb*length/b.geom.length)
                if not end1[1]>upper[1]>lower[1]>end2[1]: continue
                # Outer segments must not intersect one another.
                if _segment_gap(upper,end1,lower,end2)<EPS: continue
                mm=segment(middle,ha[1],hb[1])
                out.append(make_new('Sowilo',[aa,mm,bb],[angle_diff(a.geom.angle,target)/r['sowilo_angle'],angle_diff(b.geom.angle,target)/r['sowilo_angle'],angle_diff(middle.geom.angle,180-target)/r['sowilo_angle']]))
        return out

    def all_candidates(self,casting,chevron_rules=None):
        # Embedded-only records from V0.1 are represented by their parent's
        # components instead: no synthetic early emergence event.
        old=[c for c in self.detect() if not c.get('embedded_only',False)]
        all_rows=old+recognize_kenaz_jera(casting,chevron_rules,self)+self.stem_family()+self.sowilo()
        return sorted({c['id']:c for c in all_rows}.values(),key=lambda c:(c['first_appearance'],c['rune'],c['id']))

def recognize_all(casting,geometry_rules=None,chevron_rules=None,family_rules=None):
    return PrimitiveGraph(casting,geometry_rules,family_rules).all_candidates(casting,chevron_rules)

def overlap_ratio(child,component):
    """Same primitive with different canonical crop lengths; opposite rays do not match."""
    a={s['stick']:s for s in child['segments']}; b={s['stick']:s for s in component['segments']}
    if set(a)!=set(b): return 0.
    return min(max(0.,min(x['t_end'],b[k]['t_end'])-max(x['t_start'],b[k]['t_start'])) / min(x['t_end']-x['t_start'],b[k]['t_end']-b[k]['t_start']) for k,x in a.items())

def presentation_all(candidates,grammar,step=72):
    """Resolve containment at a replay prefix. Keep every raw candidate intact."""
    relations={r['name']:set(r['possible_children']) for r in grammar['runes']}
    active=[c for c in candidates if c['first_appearance']<=step]
    # Index by possible child name and supporting line to bound comparisons.
    index={}
    for p in active:
        for name in relations.get(p['rune'],()):
            for s in p['segments']:
                index.setdefault((name,s['stick']),[]).append(p)
    output=[]
    for c in active:
        parents=[]
        for p in index.get((c['rune'],c['segments'][0]['stick']),[]):
            if len(p['segments'])<=len(c['segments']): continue
            if contained(c,p) or any(q['rune']==c['rune'] and overlap_ratio(c,q)>=.95 for q in p.get('components',[])):
                parents.append(p['id'])
        output.append(dict(c,status='embedded' if parents else 'independent',parent_ids=sorted(set(parents))))
    return output

def template_fixture(grammar,name,scale=.52):
    r=next(r for r in grammar['runes'] if r['name']==name)
    return from_pairs([line_chord(mul(a,scale),mul(b,scale)) for a,b in r['lines']])


# Notebook cell 4 (zero-based)

GEOMETRY = dict(DEFAULT_RULES)

CHEVRONS = dict(RULES)

FAMILY = dict(FAMILY_RULES)

def detect(casting):
    return recognize_all(casting,GEOMETRY,CHEVRONS,FAMILY)

def visible(rows,step=72):
    return [x for x in presentation_all(rows,GRAMMAR,step) if x['status']=='independent']


# Notebook cell 14 (zero-based)

ENCLOSURE = dict(
    min_height=.25,
    max_height=.80,
    width_ratio_min=.48,
    width_ratio_max=.98,
    apex_error=.18,
    junction_tol=.09,
    leg_angle=12.,
    lobe_ratio_max=1.35,
    lobe_width_ratio_max=1.35,
    min_support=.28,
)

ENCLOSURE_GLYPHS = {
    'Thurisaz': 'ᚦ',
    'Wunjo': 'ᚹ',
    'Raidho': 'ᚱ',
    'Berkano': 'ᛒ',
}

@dataclass(frozen=True)
class Triangle:
    stem: Stick
    upper: Branch
    lower: Branch
    apex: tuple
    arms: tuple
    height: float
    width: float
    balance: float
    fit: float

def triangle_primitives(graph, rules):
    """
    Find real triangular enclosures sharing a near-vertical
    stem. Each triangle is calculated only once.
    """
    r = rules
    out = {s.seq: [] for s in graph.stems}

    for stem in graph.stems:
        if stem.geom.length < r['min_support']:
            continue

        up = mul(
            stem.v,
            (1 if stem.v[1] > 0 else -1)
            / stem.geom.length
        )
        right = (up[1], -up[0])

        arms = [
            b for b in graph.branches[stem.seq]
            if b.arm.geom.length >= r['min_support']
        ]

        for a, b in combinations(arms, 2):
            high, low = sorted(
                (a, b),
                key=lambda x: dot(x.vertex, up),
                reverse=True
            )

            h = dist(high.vertex, low.vertex)

            if not r['min_height'] <= h <= r['max_height']:
                continue

            hit = graph.hit(high.arm, low.arm)

            if hit is None:
                continue

            apex, u, v = hit
            delta = sub(apex, low.vertex)

            w = dot(delta, right)
            ratio = w / h
            balance = abs(dot(delta, up) / h - .5)

            if not (
                r['width_ratio_min']
                <= ratio
                <= r['width_ratio_max']
            ):
                continue

            if balance > r['apex_error']:
                continue

            if min(
                dist(apex, high.vertex),
                dist(apex, low.vertex)
            ) < EPS:
                continue

            segs = (
                segment(high.arm, high.arm_t, u),
                segment(low.arm, low.arm_t, v)
            )

            fit = abs(ratio - .70) / .30

            out[stem.seq].append(
                Triangle(
                    stem, high, low, apex,
                    segs, h, w, balance, fit
                )
            )

    return out

def triangle_errors(t, r):
    return [
        t.balance / r['apex_error'],
        t.fit
    ]

def triangle_stem(t, below, above):
    """
    Extend the highlighted stem by multiples of the
    actual triangle height.
    """
    return vertical_segment(
        t.stem,
        t.lower.stem_t,
        below * t.height,
        (1 + above) * t.height
    )

def make_enclosure(name, segs, errors, components=()):
    key = ';'.join(
        f"{s['stick']}:{s['t_start']:.8f}:{s['t_end']:.8f}"
        for s in sorted(segs, key=lambda x: x['stick'])
    )

    return dict(
        id=name + ':' + key,
        rune=name,
        glyph=ENCLOSURE_GLYPHS[name],
        first_appearance=max(s['stick'] for s in segs),
        score=score(errors),
        segments=segs,
        components=list(components)
    )

def enclosure_candidates(graph, rules=None):
    r = {**ENCLOSURE, **(rules or {})}
    triangles = triangle_primitives(graph, r)
    out = []

    for ts in triangles.values():

        for t in ts:
            err = triangle_errors(t, r)

            # ----------------------------------------
            # THURISAZ: centered triangular enclosure
            # ----------------------------------------

            st = triangle_stem(t, .5, .5)

            if st:
                out.append(
                    make_enclosure(
                        'Thurisaz',
                        [st, *t.arms],
                        err
                    )
                )

            # ----------------------------------------
            # WUNJO: upper triangular enclosure
            # ----------------------------------------

            st = triangle_stem(t, 1., 0.)

            if st:
                out.append(
                    make_enclosure(
                        'Wunjo',
                        [st, *t.arms],
                        err
                    )
                )

            # ----------------------------------------
            # RAIDHO: Wunjo with descending leg
            # ----------------------------------------

            if not st:
                continue

            used = {
                t.stem.seq,
                t.upper.arm.seq,
                t.lower.arm.seq
            }

            target = -degrees(atan2(1.1, .75))

            for b in graph.branches[t.stem.seq]:

                if b.arm.seq in used:
                    continue

                gap = dist(
                    b.vertex, t.lower.vertex
                ) / t.height

                angle = abs(b.slope - target)

                if gap > r['junction_tol']:
                    continue

                if angle > r['leg_angle']:
                    continue

                length = hypot(.75, 1.1) / .9 * t.height

                leg = signed_segment(
                    b.arm,
                    b.arm_t,
                    b.sign * length
                )

                if leg:
                    out.append(
                        make_enclosure(
                            'Raidho',
                            [st, *t.arms, leg],
                            err + [
                                gap / r['junction_tol'],
                                angle / r['leg_angle']
                            ],
                            [
                                dict(
                                    rune='Wunjo',
                                    segments=[st, *t.arms]
                                )
                            ]
                        )
                    )

        # --------------------------------------------
        # BERKANO: two compatible stacked triangles
        # --------------------------------------------

        for a, b in combinations(ts, 2):

            top, bot = sorted(
                (a, b),
                key=lambda t: t.apex[1],
                reverse=True
            )

            arms = (
                top.upper,
                top.lower,
                bot.upper,
                bot.lower
            )

            if len({x.arm.seq for x in arms}) != 4:
                continue

            h = min(top.height, bot.height)

            up = mul(
                top.stem.v,
                (1 if top.stem.v[1] > 0 else -1)
                / top.stem.geom.length
            )

            signed_gap = dot(
                sub(top.lower.vertex, bot.upper.vertex),
                up
            ) / h

            gap = abs(signed_gap)

            if gap > r['junction_tol']:
                continue

            hr = max(top.height, bot.height) / h
            wr = (
                max(top.width, bot.width)
                / min(top.width, bot.width)
            )

            if hr > r['lobe_ratio_max']:
                continue

            if wr > r['lobe_width_ratio_max']:
                continue

            st = segment(
                top.stem,
                bot.lower.stem_t,
                top.upper.stem_t
            )

            out.append(
                make_enclosure(
                    'Berkano',
                    [st, *top.arms, *bot.arms],
                    triangle_errors(top, r)
                    + triangle_errors(bot, r)
                    + [
                        gap / r['junction_tol'],
                        (hr - 1) / (r['lobe_ratio_max'] - 1),
                        (wr - 1) / (r['lobe_width_ratio_max'] - 1)
                    ]
                )
            )

    return out

def detect_v04(casting):

    graph = PrimitiveGraph(
        casting, GEOMETRY, FAMILY
    )

    rows = (
        graph.all_candidates(casting, CHEVRONS)
        + enclosure_candidates(graph, ENCLOSURE)
    )

    return sorted(
        {c['id']: c for c in rows}.values(),
        key=lambda c: (
            c['first_appearance'],
            c['rune'],
            c['id']
        )
    )


# Notebook cell 15 (zero-based)

def support_key(candidate):
    return tuple(sorted({
        s['stick'] for s in candidate['segments']
    }))

def compound_relationships(rows, step=72, min_overlap=.40):
    """
    Identify different rune identities supported by
    the same substantially overlapping geometry.

    Never suppress or modify a detection.
    """
    active = [
        x for x in presentation_all(rows, GRAMMAR, step)
        if x['status'] == 'independent'
    ]

    groups = {}

    for c in active:
        groups.setdefault(support_key(c), []).append(c)

    relationships = []

    for key, group in groups.items():

        if len(group) < 2:
            continue

        for a, b in combinations(group, 2):

            if a['rune'] == b['rune']:
                continue

            overlap = overlap_ratio(a, b)

            if overlap < min_overlap:
                continue

            relationships.append({
                'type': 'compound_candidate',
                'runes': sorted([a['rune'], b['rune']]),
                'candidate_ids': [a['id'], b['id']],
                'supporting_sticks': list(key),
                'overlap': overlap,
                'first_appearance': max(
                    a['first_appearance'],
                    b['first_appearance']
                )
            })

    return relationships


# Notebook cell 18 (zero-based)

FORK_GLYPHS = {
    'Algiz': 'ᛉ',
    'Tiwaz': 'ᛏ',
    'Eihwaz': 'ᛇ'
}

FORK_RULES = dict(
    angle_tol=9.,
    mirror_tol=12.,
    junction_tol=.075,

    algiz_half_stem=.45,
    tiwaz_stem=.90,

    eihwaz_min_stem=.65,
    eihwaz_max_stem=1.40,
    eihwaz_parallel=9.,

    min_support=.28,
)

def make_fork_rune(name, segs, errors):

    key = ';'.join(
        f"{s['stick']}:{s['t_start']:.8f}:{s['t_end']:.8f}"
        for s in sorted(segs, key=lambda x: x['stick'])
    )

    return dict(
        id=name + ':' + key,
        rune=name,
        glyph=FORK_GLYPHS[name],
        first_appearance=max(s['stick'] for s in segs),
        score=score(errors),
        segments=segs,
        components=[]
    )

def fork_candidates(graph, rules=None):
    """
    Recognize Algiz, Tiwaz and Eihwaz using the existing
    stem/branch graph.

    No additional intersection calculations.
    No modification of measured stick geometry.
    """

    r = {**FORK_RULES, **(rules or {})}
    out = []

    for stem in graph.stems:

        arms = [
            b for b in graph.branches[stem.seq]
            if b.arm.geom.length >= r['min_support']
        ]

        # ------------------------------------------------
        # ALGIZ AND TIWAZ
        # Shared symmetrical fork construction.
        # ------------------------------------------------

        specifications = (
            (
                'Algiz',
                degrees(atan2(.85, .65)),
                r['algiz_half_stem'],
                r['algiz_half_stem'] * hypot(.65, .85)
            ),
            (
                'Tiwaz',
                -degrees(atan2(.5, .65)),
                r['tiwaz_stem'],
                r['tiwaz_stem'] * hypot(.65, .5) / 2
            ),
        )

        for name, target, h, arm_len in specifications:

            right = [
                b for b in arms
                if abs(b.slope - target) <= r['angle_tol']
            ]

            left = [
                b for b in arms
                if abs(b.slope + target) <= r['angle_tol']
            ]

            for a, b in (
                (a, b) for a in right for b in left
            ):

                if a.arm.seq == b.arm.seq:
                    continue

                mirror = abs(a.slope + b.slope)

                gap = dist(a.vertex, b.vertex)

                max_gap = r['junction_tol'] * arm_len

                if mirror > r['mirror_tol']:
                    continue

                if gap > max_gap:
                    continue

                # Algiz: stem extends above and below
                # the fork junction.

                if name == 'Algiz':

                    anchor = (
                        a.stem_t + b.stem_t
                    ) / 2

                    st = vertical_segment(
                        stem, anchor, h, h
                    )

                # Tiwaz: stem terminates at the top
                # of the arrow-shaped fork.

                else:

                    top = max(
                        (a, b),
                        key=lambda x: x.vertex[1]
                    )

                    st = vertical_segment(
                        stem, top.stem_t, h, 0
                    )

                # Right-facing ray.

                sa = signed_segment(
                    a.arm,
                    a.arm_t,
                    a.sign * arm_len
                )

                # Left-facing ray.

                sb = signed_segment(
                    b.arm,
                    b.arm_t,
                    -b.sign * arm_len
                )

                if not (st and sa and sb):
                    continue

                errors = [
                    abs(a.slope - target) / r['angle_tol'],
                    abs(b.slope + target) / r['angle_tol'],
                    mirror / r['mirror_tol'],
                    gap / max_gap
                ]

                out.append(
                    make_fork_rune(
                        name,
                        [st, sa, sb],
                        errors
                    )
                )

        # ------------------------------------------------
        # EIHWAZ
        # Parallel branches on opposite sides and ends.
        # ------------------------------------------------

        target = -degrees(atan2(.35, .55))

        branches = [
            b for b in arms
            if abs(b.slope - target) <= r['angle_tol']
        ]

        for a, b in combinations(branches, 2):

            top, bot = sorted(
                (a, b),
                key=lambda x: x.vertex[1],
                reverse=True
            )

            h = dist(top.vertex, bot.vertex)

            if not (
                r['eihwaz_min_stem']
                <= h
                <= r['eihwaz_max_stem']
            ):
                continue

            parallel = abs(top.slope - bot.slope)

            if parallel > r['eihwaz_parallel']:
                continue

            # Scale both branch lengths from the
            # actual intersection-to-intersection stem.

            length = h * hypot(.55, .35) / 2

            hi = signed_segment(
                top.arm,
                top.arm_t,
                top.sign * length
            )

            lo = signed_segment(
                bot.arm,
                bot.arm_t,
                -bot.sign * length
            )

            if not (hi and lo):
                continue

            st = segment(
                stem,
                top.stem_t,
                bot.stem_t
            )

            out.append(
                make_fork_rune(
                    'Eihwaz',
                    [st, hi, lo],
                    [
                        abs(top.slope-target) / r['angle_tol'],
                        abs(bot.slope-target) / r['angle_tol'],
                        parallel / r['eihwaz_parallel']
                    ]
                )
            )

    return out

def detect_v05(casting):

    graph = PrimitiveGraph(
        casting, GEOMETRY, FAMILY
    )

    rows = (
        graph.all_candidates(casting, CHEVRONS)
        + enclosure_candidates(graph, ENCLOSURE)
        + fork_candidates(graph, FORK_RULES)
    )

    return sorted(
        {c['id']: c for c in rows}.values(),
        key=lambda c: (
            c['first_appearance'],
            c['rune'],
            c['id']
        )
    )


# Notebook cell 21 (zero-based)

PAIRED_GLYPHS = {
    'Uruz': 'ᚢ',
    'Hagalaz': 'ᚺ',
    'Ehwaz': 'ᛖ',
    'Mannaz': 'ᛗ'
}

PAIRED = dict(
    min_width=.30,
    max_width=.80,
    parallel=9.,
    slope_tol=9.,
    level_tol=.15,
    center_tol=.16,
    stem_tol=.18,
    min_support=.30
)

def paired_rune(name, segs, errors, components=()):

    key = ';'.join(
        f"{s['stick']}:{s['t_start']:.8f}:{s['t_end']:.8f}"
        for s in sorted(segs, key=lambda x: x['stick'])
    )

    return dict(
        id=name + ':' + key,
        rune=name,
        glyph=PAIRED_GLYPHS[name],
        first_appearance=max(s['stick'] for s in segs),
        score=score(errors),
        segments=segs,
        components=list(components)
    )

def x_at_y(s, y=0.):

    return (
        s.p[0]
        + (y - s.p[1]) * s.v[0] / s.v[1]
    )

def paired_candidates(graph, rules=None):

    r = {**PAIRED, **(rules or {})}
    out = []

    def ends(s, seg):

        return sorted(
            (
                s.at(seg['t_start']),
                s.at(seg['t_end'])
            ),
            key=lambda p: p[1]
        )

    def emit(
        name, L, R, ls, rs,
        other, errors, components=()
    ):

        if not (ls and rs):
            return

        lb, lt = ends(L, ls)
        rb, rt = ends(R, rs)

        w = (
            rb[0] - lb[0]
            + rt[0] - lt[0]
        ) / 2

        # Ensure the stems remain distinct and
        # do not cross within the highlighted region.

        if w <= EPS:
            return

        if min(
            rb[0] - lb[0],
            rt[0] - lt[0]
        ) <= EPS:
            return

        if _segment_gap(lb, lt, rb, rt) < EPS:
            return

        # All four current templates have an
        # approximately level, open base.

        base = abs(lb[1] - rb[1]) / w

        if base > r['stem_tol']:
            return

        out.append(
            paired_rune(
                name,
                [ls, rs, *other],
                errors + [base / r['stem_tol']],
                components
            )
        )

    def width(p, q):

        w = q[0] - p[0]

        if r['min_width'] <= w <= r['max_width']:
            return w

        return None

    # --------------------------------------------------------
    # SHARED PAIRED-STEM PRIMITIVE
    # --------------------------------------------------------

    for L, R in combinations(graph.stems, 2):

        L, R = sorted((L, R), key=x_at_y)

        par = angle_diff(
            L.geom.angle, R.geom.angle
        )

        if par > r['parallel']:
            continue

        pe = par / r['parallel']

        left = {
            s.seq: (s, graph.hit(L, s))
            for s in graph.sticks
            if s.seq not in (L.seq, R.seq)
            and s.geom.length >= r['min_support']
            and graph.hit(L, s) is not None
        }

        right = {
            s.seq: (s, graph.hit(R, s))
            for s in graph.sticks
            if s.seq not in (L.seq, R.seq)
            and s.geom.length >= r['min_support']
            and graph.hit(R, s) is not None
        }

        bridges = []

        # A bridge intersects both vertical stems.

        for i in left.keys() & right.keys():

            s, a = left[i]
            _, b = right[i]

            w = width(a[0], b[0])

            if w is None:
                continue

            slope = degrees(
                atan2(b[0][1] - a[0][1], w)
            )

            bridges.append((s, a, b, w, slope))

            if abs(a[2] - b[2]) <= EPS:
                continue

            bar = segment(s, a[2], b[2])

            # ------------------------------------------------
            # URUZ AND HAGALAZ
            #
            # Same bridge primitive, different proportions
            # and positions along the vertical stems.
            # ------------------------------------------------

            specs = (
                (
                    'Uruz',
                    -degrees(atan2(.6, 1)),
                    2., 0.,
                    1.4, 0.
                ),
                (
                    'Hagalaz',
                    -degrees(atan2(1.1, 1)),
                    1.55, .45,
                    .45, 1.55
                )
            )

            for name, target, ld, lu, rd, ru in specs:

                err = abs(slope - target)

                if err > r['slope_tol']:
                    continue

                ls = vertical_segment(
                    L, a[1], ld*w, lu*w
                )

                rs = vertical_segment(
                    R, b[1], rd*w, ru*w
                )

                emit(
                    name, L, R, ls, rs,
                    [bar],
                    [pe, err/r['slope_tol']]
                )

        # ----------------------------------------------------
        # MANNAZ
        # Two opposite bridges forming a crossing.
        # ----------------------------------------------------

        rising = [
            v for v in bridges
            if abs(v[4] - 45) <= r['slope_tol']
        ]

        falling = [
            v for v in bridges
            if abs(v[4] + 45) <= r['slope_tol']
        ]

        for c, cl, cr, wc, sc in rising:

            for d, dl, dr, wd, sd in falling:

                if c.seq == d.seq:
                    continue

                hit = graph.hit(c, d)

                if hit is None:
                    continue

                p, u, v = hit

                # Crossing must fall within both bridges.

                if not (
                    min(cl[2], cr[2]) + EPS
                    < u <
                    max(cl[2], cr[2]) - EPS

                    and

                    min(dl[2], dr[2]) + EPS
                    < v <
                    max(dl[2], dr[2]) - EPS
                ):
                    continue

                if not (
                    dl[0][1] > cl[0][1]
                    and cr[0][1] > dr[0][1]
                ):
                    continue

                w = (wc + wd) / 2

                level = max(
                    abs(dl[0][1] - cr[0][1]),
                    abs(cl[0][1] - dr[0][1])
                ) / w

                center = dist(
                    p,
                    mid(
                        mid(cl[0], dl[0]),
                        mid(cr[0], dr[0])
                    )
                ) / w

                if level > r['level_tol']:
                    continue

                if center > r['center_tol']:
                    continue

                # Extend stems below the crossing,
                # distinguishing Mannaz from Dagaz.

                ls = vertical_segment(
                    L,
                    dl[1],
                    dist(dl[0], cl[0]) + w,
                    0
                )

                rs = vertical_segment(
                    R,
                    cr[1],
                    dist(cr[0], dr[0]) + w,
                    0
                )

                xs = [
                    segment(c, cl[2], cr[2]),
                    segment(d, dl[2], dr[2])
                ]

                emit(
                    'Mannaz', L, R, ls, rs,
                    xs,
                    [
                        pe,
                        abs(sc-45)/r['slope_tol'],
                        abs(sd+45)/r['slope_tol'],
                        level/r['level_tol'],
                        center/r['center_tol']
                    ],
                    [
                        dict(
                            rune='Gebo',
                            segments=xs
                        )
                    ]
                )

        # ----------------------------------------------------
        # EHWAZ
        # Opposite diagonals forming a central valley.
        # These need not intersect both stems.
        # ----------------------------------------------------

        target = degrees(atan2(.65, .5))

        down = [
            (s, h)
            for s, h in left.values()
            if angle_diff(
                s.geom.angle, 180-target
            ) <= r['slope_tol']
        ]

        up = [
            (s, h)
            for s, h in right.values()
            if angle_diff(
                s.geom.angle, target
            ) <= r['slope_tol']
        ]

        for c, a in down:

            for d, b in up:

                if c.seq == d.seq:
                    continue

                w = width(a[0], b[0])
                hit = graph.hit(c, d)

                if w is None or hit is None:
                    continue

                p, u, v = hit

                # The valley must be between the stems
                # and below both upper junctions.

                if not (
                    a[0][0] + EPS
                    < p[0] <
                    b[0][0] - EPS

                    and

                    p[1] < min(
                        a[0][1], b[0][1]
                    ) - EPS
                ):
                    continue

                level = abs(
                    a[0][1] - b[0][1]
                ) / w

                center = abs(
                    p[0] - mid(a[0], b[0])[0]
                ) / w

                if level > r['level_tol']:
                    continue

                if center > r['center_tol']:
                    continue

                ls = vertical_segment(
                    L, a[1], 2*w, 0
                )

                rs = vertical_segment(
                    R, b[1], 2*w, 0
                )

                vs = [
                    segment(c, a[2], u),
                    segment(d, b[2], v)
                ]

                emit(
                    'Ehwaz', L, R, ls, rs,
                    vs,
                    [
                        pe,
                        angle_diff(
                            c.geom.angle,
                            180-target
                        ) / r['slope_tol'],
                        angle_diff(
                            d.geom.angle,
                            target
                        ) / r['slope_tol'],
                        level/r['level_tol'],
                        center/r['center_tol']
                    ]
                )

    return out

def detect_v06(casting):

    graph = PrimitiveGraph(
        casting, GEOMETRY, FAMILY
    )

    rows = (
        graph.all_candidates(casting, CHEVRONS)
        + enclosure_candidates(graph, ENCLOSURE)
        + fork_candidates(graph, FORK_RULES)
        + paired_candidates(graph, PAIRED)
    )

    return sorted(
        {c['id']: c for c in rows}.values(),
        key=lambda c: (
            c['first_appearance'],
            c['rune'],
            c['id']
        )
    )


# Notebook cell 24 (zero-based)

FINAL_GLYPHS = {
    'Perthro': 'ᛈ',
    'Othala': 'ᛟ'
}

FINAL_RULES = dict(
    hook_angle=10.,
    hook_min_height=.65,
    hook_max_height=1.40,
    hook_inner_ratio=.283,
    hook_ratio_tol=.07,
    hook_mirror=.12,

    diamond_parallel=8.,
    diamond_axis=12.,
    diamond_orthogonal=10.,
    diamond_center=.12,
    diamond_side_ratio=1.25,
    diamond_min_width=.40,
    diamond_min_ratio=1.0,
    diamond_max_ratio=1.45,

    leg_ratio=1.0,
    min_support=.28
)

def final_rune(name, segs, errors, components=()):

    key = ';'.join(
        f"{s['stick']}:{s['t_start']:.8f}:{s['t_end']:.8f}"
        for s in sorted(segs, key=lambda x: x['stick'])
    )

    return dict(
        id=name + ':' + key,
        rune=name,
        glyph=FINAL_GLYPHS[name],
        first_appearance=max(s['stick'] for s in segs),
        score=score(errors),
        segments=segs,
        components=list(components)
    )

def perthro_candidates(graph, r):

    out = []

    rising = [
        s for s in graph.sticks
        if angle_diff(s.geom.angle,45) <= r['hook_angle']
        and s.geom.length >= r['min_support']
    ]

    falling = [
        s for s in graph.sticks
        if angle_diff(s.geom.angle,135) <= r['hook_angle']
        and s.geom.length >= r['min_support']
    ]

    for stem in graph.stems:

        # Find hooks consisting of two angled strokes.
        # The inner stroke intersects the stem.
        # The outer stroke intersects the inner stroke.

        def hooks(inner_group, outer_group):

            for inner in inner_group:

                a = graph.hit(stem, inner)

                if a is None:
                    continue

                for outer in outer_group:

                    b = graph.hit(inner, outer)

                    if b is None:
                        continue

                    delta = sub(b[0], a[0])

                    if delta[0] <= EPS:
                        continue

                    length = norm(delta)

                    low = (
                        r['hook_inner_ratio']
                        - r['hook_ratio_tol']
                    ) * r['hook_min_height']

                    high = (
                        r['hook_inner_ratio']
                        + r['hook_ratio_tol']
                    ) * r['hook_max_height']

                    if not low <= length <= high:
                        continue

                    sg = 1 if outer.v[0] > 0 else -1

                    tip = signed_segment(
                        outer,
                        b[2],
                        sg * length
                    )

                    if tip is None:
                        continue

                    yield (
                        inner, outer, a, b, length,
                        segment(inner, a[2], b[1]),
                        tip
                    )

        tops = list(hooks(falling, rising))
        bottoms = list(hooks(rising, falling))

        # Pair compatible upper and lower hooks.

        for ti, to, a, b, l, si, so in tops:

            for bi, bo, c, d, k, ui, uo in bottoms:

                if len({
                    stem.seq,
                    ti.seq, to.seq,
                    bi.seq, bo.seq
                }) != 5:
                    continue

                if a[0][1] <= c[0][1]:
                    continue

                h = dist(a[0], c[0])

                if not (
                    r['hook_min_height']
                    <= h
                    <= r['hook_max_height']
                ):
                    continue

                errs = [
                    abs(l/h - r['hook_inner_ratio']),
                    abs(k/h - r['hook_inner_ratio'])
                ]

                if max(errs) > r['hook_ratio_tol']:
                    continue

                # Compare hook symmetry in a local
                # coordinate system aligned with the stem.

                up = mul(
                    stem.v,
                    (1 if stem.v[1] > 0 else -1)
                    / stem.geom.length
                )

                right = (up[1], -up[0])

                q = sub(b[0], a[0])
                v = sub(d[0], c[0])

                mirror = hypot(
                    dot(sub(q,v), right),
                    dot(add(q,v), up)
                ) / h

                if mirror > r['hook_mirror']:
                    continue

                # The two highlighted hooks must
                # remain spatially separate.

                def points(s, seg):

                    return (
                        s.at(seg['t_start']),
                        s.at(seg['t_end'])
                    )

                overlap = any(
                    _segment_gap(
                        *points(s,x),
                        *points(t,y)
                    ) <= EPS
                    for s,x in [(ti,si),(to,so)]
                    for t,y in [(bi,ui),(bo,uo)]
                )

                if overlap:
                    continue

                st = segment(stem, a[1], c[1])

                segs = [st, si, so, ui, uo]

                errors = (
                    [e/r['hook_ratio_tol'] for e in errs]
                    + [mirror/r['hook_mirror']]
                    + [
                        angle_diff(
                            s.geom.angle, target
                        ) / r['hook_angle']
                        for s,target in [
                            (ti,135), (to,45),
                            (bi,45), (bo,135)
                        ]
                    ]
                )

                out.append(
                    final_rune(
                        'Perthro',
                        segs,
                        errors
                    )
                )

    return out

def diamond_cycles(graph, r):
    """
    Find closed convex quadrilaterals formed by
    two pairs of approximately parallel diagonals.

    At this stage, impose no overall orientation
    or aspect ratio.
    """

    groups = [
        [
            s for s in graph.sticks
            if lo <= s.geom.angle <= hi
            and s.geom.length >= r['min_support']
        ]
        for lo,hi in [(15,75),(105,165)]
    ]

    pairs = [
        [
            (a,b)
            for a,b in combinations(group,2)
            if angle_diff(
                a.geom.angle, b.geom.angle
            ) <= r['diamond_parallel']
        ]
        for group in groups
    ]

    for a,b in pairs[0]:

        for c,d in pairs[1]:

            ac = graph.hit(a,c)
            ad = graph.hit(a,d)
            bc = graph.hit(b,c)
            bd = graph.hit(b,d)

            if not all((ac,ad,bc,bd)):
                continue

            v = [
                ac[0], bc[0],
                bd[0], ad[0]
            ]

            edges = [
                sub(v[(i+1)%4],v[i])
                for i in range(4)
            ]

            turns = [
                cross(edges[i],edges[(i+1)%4])
                for i in range(4)
            ]

            convex = (
                all(t > EPS for t in turns)
                or all(t < -EPS for t in turns)
            )

            if not convex:
                continue

            lengths = [
                norm(e) for e in edges
            ]

            if min(lengths) <= EPS:
                continue

            # Edge i connects vertex i to vertex i+1.

            ss = [c,b,d,a]

            tt = [
                (ac[2],bc[2]),
                (bc[1],bd[1]),
                (bd[2],ad[2]),
                (ad[1],ac[1])
            ]

            yield v,ss,tt,lengths

def othala_candidates(graph, r):

    out = []

    for v,ss,tt,lengths in diamond_cycles(graph,r):

        side = max(lengths)/min(lengths)

        if side > r['diamond_side_ratio']:
            continue

        top = max(
            range(4),
            key=lambda i: v[i][1]
        )

        bottom = (top+2)%4

        a = v[(top+1)%4]
        b = v[(top-1)%4]

        dv = sub(v[top],v[bottom])
        dh = sub(a,b)

        h = norm(dv)
        w = norm(dh)

        if w < r['diamond_min_width'] or h <= EPS:
            continue

        if not (
            r['diamond_min_ratio']
            <= h/w
            <= r['diamond_max_ratio']
        ):
            continue

        ve = angle_diff(axis_angle(dv),90)
        he = angle_diff(axis_angle(dh),0)

        orth = abs(
            90-angle_diff(
                axis_angle(dv),
                axis_angle(dh)
            )
        )

        center = dist(
            mid(v[top],v[bottom]),
            mid(a,b)
        ) / min(w,h)

        if max(ve,he) > r['diamond_axis']:
            continue

        if orth > r['diamond_orthogonal']:
            continue

        if center > r['diamond_center']:
            continue

        if not v[bottom][1] < min(a[1],b[1]):
            continue

        # Preserve the original four-sided diamond
        # separately from the extended geometry.

        core = [
            segment(s,t,u)
            for s,(t,u) in zip(ss,tt)
        ]

        segs = list(core)
        ok = True

        # Extend both lower sides past their common
        # intersection, using the actual supporting
        # chord intervals.

        for i in ((bottom-1)%4,bottom):

            s = ss[i]
            t,u = tt[i]

            tip,other = (
                (u,t)
                if (i+1)%4 == bottom
                else (t,u)
            )

            end = (
                tip
                + r['leg_ratio']*(tip-other)
            )

            if not -EPS <= end <= 1+EPS:

                ok = False
                break

            segs[i] = segment(s,other,end)

        if not ok:
            continue

        errors = [
            ve/r['diamond_axis'],
            he/r['diamond_axis'],
            orth/r['diamond_orthogonal'],
            center/r['diamond_center'],
            (side-1)/(r['diamond_side_ratio']-1)
        ]

        components = [
            dict(
                rune='Ingwaz',
                variant=(
                    'vertical diamond primitive; '
                    'not standalone recognition'
                ),
                segments=core
            )
        ]

        out.append(
            final_rune(
                'Othala',
                segs,
                errors,
                components
            )
        )

    return out

def detect_v07(casting):

    graph = PrimitiveGraph(
        casting, GEOMETRY, FAMILY
    )

    rows = (
        graph.all_candidates(casting, CHEVRONS)
        + enclosure_candidates(graph, ENCLOSURE)
        + fork_candidates(graph, FORK_RULES)
        + paired_candidates(graph, PAIRED)
        + perthro_candidates(graph, FINAL_RULES)
        + othala_candidates(graph, FINAL_RULES)
    )

    return sorted(
        {c['id']: c for c in rows}.values(),
        key=lambda c: (
            c['first_appearance'],
            c['rune'],
            c['id']
        )
    )


# Notebook cell 27 (zero-based)

from collections import defaultdict, Counter

from copy import deepcopy

DUP_ABS = .035

DUP_REL = .08

def geometry_record(candidate, sticks):

    lines = []

    for s in candidate['segments']:

        st = sticks[s['stick']]

        lines.append((
            st.at(s['t_start']),
            st.at(s['t_end'])
        ))

    pts = [
        p
        for line in lines
        for p in line
    ]

    lo = tuple(
        min(p[k] for p in pts)
        for k in (0,1)
    )

    hi = tuple(
        max(p[k] for p in pts)
        for k in (0,1)
    )

    return lines, mid(lo,hi), dist(lo,hi)

def same_formation(
    a, b,
    abs_tol=DUP_ABS,
    rel_tol=DUP_REL
):
    """
    Compare highlighted strokes in absolute
    casting coordinates.

    Translation, rotation and scaling are
    NOT permitted when matching duplicates.
    """

    A, ca, da = a
    B, cb, db = b

    if len(A) != len(B):
        return False

    tol = min(
        abs_tol,
        rel_tol * min(da,db)
    )

    # Cheap spatial rejection.

    if dist(ca,cb) > 2**.5 * tol:
        return False

    if abs(da-db) > 2**.5 * 2 * tol:
        return False

    # Determine which strokes can match.
    # Endpoint direction is irrelevant.

    options = []

    for p,q in A:

        js = []

        for j,(u,v) in enumerate(B):

            forward = max(
                dist(p,u), dist(q,v)
            )

            reverse = max(
                dist(p,v), dist(q,u)
            )

            if min(forward,reverse) <= tol:
                js.append(j)

        if not js:
            return False

        options.append(js)

    # Require a one-to-one stroke assignment.
    # At most five strokes makes this cheap.

    options.sort(key=len)

    def match(i,used):

        if i == len(options):
            return True

        return any(
            match(i+1, used | (1<<j))
            for j in options[i]
            if not used & (1<<j)
        )

    return match(0,0)

def presentation_v08(
    casting, rows,
    step=72,
    abs_tol=DUP_ABS,
    rel_tol=DUP_REL
):
    """
    Resolve existing hierarchical relationships,
    then consolidate same-rune near duplicates.

    All raw candidate records remain intact.
    """

    state = presentation_all(
        rows, GRAMMAR, step
    )

    sticks = {
        s.seq:s
        for s in casting_sticks(casting)
    }

    groups = defaultdict(list)

    for c in state:

        c['representative_id'] = None
        c['duplicate_ids'] = []

        if c['status'] == 'independent':
            groups[c['rune']].append(c)

    # Compare candidates only with others
    # of the SAME rune identity.

    for group in groups.values():

        representatives = []

        # Prefer the best geometric fit.
        # Resolve ties deterministically.

        ordered = sorted(
            group,
            key=lambda c: (
                -c['score'],
                c['first_appearance'],
                c['id']
            )
        )

        for c in ordered:

            g = geometry_record(c,sticks)

            parent = next(
                (
                    p for p,pg in representatives
                    if same_formation(
                        g,pg,abs_tol,rel_tol
                    )
                ),
                None
            )

            if parent is None:

                c['representative_id'] = c['id']

                representatives.append((c,g))

            else:

                c['status'] = 'duplicate'

                c['representative_id'] = (
                    parent['id']
                )

                parent['duplicate_ids'].append(
                    c['id']
                )

    return state

def visible_v08(casting,rows,step=72):

    return [
        c for c in presentation_v08(
            casting,rows,step,
            abs_tol=DUP_ABS,
            rel_tol=DUP_REL
        )
        if c['status'] == 'independent'
    ]


# Notebook cell 31 (zero-based)

MIN_RUNE_SIZE = .35

MIN_STROKE_SIZE = .075

QUALITY_POWER = 3.

QUALITY_MIN = {}

def measure_candidates(casting, rows):

    sticks = {
        s.seq: s
        for s in casting_sticks(casting)
    }

    metrics = {}

    for c in rows:

        g = geometry_record(c, sticks)
        lines, center, diagonal = g

        points = [
            p
            for line in lines
            for p in line
        ]

        # Maximum actual endpoint separation,
        # normalized to the casting diameter.

        span = max(
            dist(p, q)
            for p, q in combinations(points, 2)
        ) / 2

        stroke = min(
            dist(a, b)
            for a, b in lines
        ) / 2

        metrics[c['id']] = dict(
            geometry=g,
            size=span,
            min_stroke=stroke
        )

    return metrics

def representative_rank(c):

    return (
        -c['rank_value'],
        -c['score'],
        -c['size'],
        c['first_appearance'],
        c['id']
    )

def select_formations(
    casting,
    rows,
    step=72,
    min_size=MIN_RUNE_SIZE,
    min_stroke=MIN_STROKE_SIZE,
    quality_min=None,
    quality_power=QUALITY_POWER,
    metrics=None
):

    if metrics is None:
        metrics = measure_candidates(
            casting, rows
        )

    accepted = []
    rejected = []

    # --------------------------------------------------------
    # 1. Apply size and conformity requirements BEFORE
    #    resolving hierarchical relationships.
    # --------------------------------------------------------

    for c in rows:

        if c['first_appearance'] > step:
            continue

        m = metrics[c['id']]

        n = c['rune']
        q = c['score']

        floor = (quality_min or {}).get(n, 0.)

        info = dict(
            size=m['size'],
            min_stroke=m['min_stroke'],
            rank_value=m['size'] * q**quality_power,
            representative_id=None,
            duplicate_ids=[]
        )

        reasons = []

        if m['size'] < min_size:
            reasons.append('span')

        if m['min_stroke'] < min_stroke:
            reasons.append('stroke')

        if q < floor:
            reasons.append('quality')

        x = dict(c, **info)

        if reasons:

            rejected.append(
                dict(
                    x,
                    status='rejected',
                    rejection_reasons=reasons,
                    parent_ids=[]
                )
            )

        else:
            accepted.append(x)

    # --------------------------------------------------------
    # 2. Resolve geometrically embedded runes.
    # --------------------------------------------------------

    state = presentation_all(
        accepted, GRAMMAR, step
    )

    groups = defaultdict(list)

    for x in state:

        if x['status'] == 'independent':
            groups[x['rune']].append(x)

    # --------------------------------------------------------
    # 3. Consolidate near-identical formations.
    #
    #    Prefer size AND conformity when choosing the
    #    representative of a duplicate cluster.
    # --------------------------------------------------------

    for group in groups.values():

        reps = []

        for x in sorted(
            group,
            key=representative_rank
        ):

            g = metrics[x['id']]['geometry']

            parent = next(
                (
                    p for p in reps
                    if same_formation(
                        g,
                        metrics[p['id']]['geometry']
                    )
                ),
                None
            )

            if parent is None:

                x['representative_id'] = x['id']

                reps.append(x)

            else:

                x['status'] = 'duplicate'

                x['representative_id'] = (
                    parent['id']
                )

                parent['duplicate_ids'].append(
                    x['id']
                )

    state += rejected

    # --------------------------------------------------------
    # 4. Summarize each rune identity.
    #
    #    One primary highlight per rune.
    #    All other occurrences remain available.
    # --------------------------------------------------------

    summary = {}

    by_name = defaultdict(list)

    for x in state:
        by_name[x['rune']].append(x)

    for n, group in by_name.items():

        tally = Counter(
            x['status'] for x in group
        )

        occurrences = sorted(
            [
                x for x in group
                if x['status'] == 'independent'
            ],
            key=representative_rank
        )

        summary[n] = dict(

            representative=(
                occurrences[0]
                if occurrences else None
            ),

            occurrence_count=len(occurrences),

            other_count=max(
                0, len(occurrences)-1
            ),

            raw_count=len(group),

            duplicate_count=tally['duplicate'],

            embedded_count=tally['embedded'],

            rejected_count=tally['rejected'],

            occurrence_ids=[
                x['id'] for x in occurrences
            ],

            earliest_surviving=min(
                (
                    x['first_appearance']
                    for x in occurrences
                ),
                default=None
            )
        )

    return state, summary


# Notebook cell 35 (zero-based)

def detect_bold(casting):

    graph = PrimitiveGraph(
        casting,
        BOLD_GEOMETRY,
        BOLD_FAMILY
    )

    rows = (
        graph.all_candidates(
            casting, BOLD_CHEVRONS
        )
        + enclosure_candidates(graph, ENCLOSURE)
        + fork_candidates(graph, BOLD_FORK)
        + paired_candidates(graph, PAIRED)
        + perthro_candidates(graph, FINAL_RULES)
        + othala_candidates(graph, FINAL_RULES)
    )

    return sorted(
        {c['id']: c for c in rows}.values(),
        key=lambda c: (
            c['first_appearance'],
            c['rune'],
            c['id']
        )
    )


# Notebook cell 36 (zero-based)

from math import exp

BOLD_QUALITY = {}

def bold_rank(candidate):

    s = candidate['size']
    q = candidate['score']

    excess = max(
        0., s - BOLD_IDEAL_MAX
    )

    weight = exp(
        -(excess / BOLD_SIZE_FALLOFF)**2
    )

    return s * q**QUALITY_POWER * weight

def select_bold(
    casting,
    rows,
    step=72,
    metrics=None
):

    state, summary = select_formations(
        casting,
        rows,
        step=step,
        min_size=BOLD_MIN_SIZE,
        min_stroke=BOLD_MIN_STROKE,
        quality_min=BOLD_QUALITY,
        metrics=metrics
    )

    groups = defaultdict(list)

    for x in state:

        if x['status'] == 'independent':

            x['presentation_rank'] = bold_rank(x)

            groups[x['rune']].append(x)

    for name, occurrences in groups.items():

        ordered = sorted(
            occurrences,
            key=lambda x: (
                -x['presentation_rank'],
                -x['score'],
                x['first_appearance'],
                x['id']
            )
        )

        s = summary[name]

        s['representative'] = ordered[0]

        s['occurrence_ids'] = [
            x['id'] for x in ordered
        ]

        s['in_preferred_range'] = (
            BOLD_MIN_SIZE
            <= ordered[0]['size']
            <= BOLD_IDEAL_MAX
        )

    return state, summary


# Notebook cell 39 (zero-based)

def detect_calibration(casting):

    rows = detect_bold(casting)

    sticks = {
        s.seq:s
        for s in casting_sticks(casting)
    }

    out = []

    for x in rows:

        y = dict(x)

        # Isa's conformity should describe orientation,
        # not reward length already measured elsewhere.

        if y['rune'] == 'Isa':

            s = sticks[y['segments'][0]['stick']]

            error = angle_diff(
                s.geom.angle,90
            )

            y['original_score'] = y['score']

            y['score'] = score([
                error / BOLD_GEOMETRY['isa_angle']
            ])

        out.append(y)

    return out


# Notebook cell 41 (zero-based)

def select_calibrated(
    casting,
    rows,
    step=72,
    metrics=None,
    quality_min=None
):

    if quality_min is None:
        quality_min = CAL_QUALITY

    state,summary = select_formations(
        casting,
        rows,
        step=step,
        min_size=BOLD_MIN_SIZE,
        min_stroke=BOLD_MIN_STROKE,
        quality_min=quality_min,
        metrics=metrics
    )

    groups = defaultdict(list)

    for x in state:

        if x['status'] != 'independent':
            continue

        x['presentation_rank'] = bold_rank(x)

        groups[x['rune']].append(x)

    for name,occurrences in groups.items():

        ordered = sorted(
            occurrences,
            key=lambda x:(
                -x['presentation_rank'],
                -x['score'],
                x['first_appearance'],
                x['id']
            )
        )

        s = summary[name]

        s['representative'] = ordered[0]

        s['occurrence_ids'] = [
            x['id'] for x in ordered
        ]

        s['in_preferred_range'] = (
            BOLD_MIN_SIZE
            <= ordered[0]['size']
            <= BOLD_IDEAL_MAX
        )

    return state,summary


# Notebook cell 46 (zero-based)

def qualified_compounds(
    state,
    min_overlap=.40
):

    groups = defaultdict(list)

    for x in state:

        if x['status'] == 'independent':

            groups[support_key(x)].append(x)

    relations = []

    for key,group in groups.items():

        if len(group) < 2:
            continue

        for a,b in combinations(group,2):

            if a['rune'] == b['rune']:
                continue

            overlap = overlap_ratio(a,b)

            if overlap < min_overlap:
                continue

            relations.append(dict(
                runes=sorted([
                    a['rune'],
                    b['rune']
                ]),
                candidate_ids=sorted([
                    a['id'],b['id']
                ]),
                supporting_sticks=list(key),
                overlap=float(overlap),
                formation_step=max(
                    a['first_appearance'],
                    b['first_appearance']
                )
            ))

    return sorted(
        relations,
        key=lambda r:(
            r['runes'],
            r['candidate_ids']
        )
    )


# Notebook cell 47 (zero-based)

def reading_snapshot(
    casting,
    rows,
    step,
    metrics
):

    state,summary = select_calibrated(
        casting,
        rows,
        step=step,
        metrics=metrics,
        quality_min=APPROVED_QUALITY
    )

    shown = {}

    for name,s in summary.items():

        x = s['representative']

        if x is None:
            continue

        shown[name] = dict(
            rune=name,
            glyph=x['glyph'],
            primary_id=x['id'],
            primary_step=x['first_appearance'],
            occurrence_count=s['occurrence_count'],
            occurrence_ids=list(
                s['occurrence_ids']
            ),
            earliest_surviving=(
                s['earliest_surviving']
            ),
            size=float(x['size']),
            quality=float(x['score']),
            presentation_rank=float(
                x['presentation_rank']
            )
        )

    compounds = qualified_compounds(state)

    return dict(
        shown=shown,
        compounds=compounds,
        statuses={
            x['id']:dict(
                status=x['status'],
                parent_ids=list(
                    x.get('parent_ids',[])
                )
            )
            for x in state
        }
    )

def build_reading_timeline(casting):

    n = len(casting['chords'])

    rows = detect_calibration(casting)

    metrics = measure_candidates(
        casting,rows
    )

    by_id = {
        x['id']:x for x in rows
    }

    change_steps = {
        x['first_appearance']
        for x in rows
    }

    frames = {}
    events = []
    first_shown = {}

    previous = dict(
        shown={},
        compounds=[],
        statuses={}
    )

    frames[0] = previous

    for step in range(1,n+1):

        # No new candidate means no change
        # to the recognition state.

        if step not in change_steps:

            frames[step] = previous
            continue

        current = reading_snapshot(
            casting,rows,step,metrics
        )

        before = previous['shown']
        after = current['shown']

        # --------------------------------------------
        # Rune presentation changes
        # --------------------------------------------

        for name in sorted(
            set(before) | set(after)
        ):

            old = before.get(name)
            new = after.get(name)

            if old is None:

                returning = name in first_shown

                first_shown.setdefault(
                    name,step
                )

                events.append(dict(
                    step=step,
                    event=(
                        'reappeared'
                        if returning
                        else 'emerged'
                    ),
                    rune=name,
                    primary_id=new['primary_id'],
                    occurrence_count=(
                        new['occurrence_count']
                    )
                ))

            elif new is None:

                # Determine whether the previously
                # independent occurrences are now embedded.

                parents = set()

                for cid in old['occurrence_ids']:

                    status = current[
                        'statuses'
                    ].get(cid,{})

                    parents.update(
                        status.get(
                            'parent_ids',[]
                        )
                    )

                events.append(dict(
                    step=step,
                    event=(
                        'embedded'
                        if parents
                        else 'withdrawn'
                    ),
                    rune=name,
                    previous_primary_id=(
                        old['primary_id']
                    ),
                    parent_ids=sorted(parents),
                    parent_runes=sorted({
                        by_id[p]['rune']
                        for p in parents
                        if p in by_id
                    })
                ))

            else:

                if (
                    old['primary_id']
                    != new['primary_id']
                ):

                    events.append(dict(
                        step=step,
                        event='primary_changed',
                        rune=name,
                        previous_primary_id=(
                            old['primary_id']
                        ),
                        primary_id=new['primary_id']
                    ))

                if (
                    old['occurrence_count']
                    != new['occurrence_count']
                ):

                    events.append(dict(
                        step=step,
                        event='count_changed',
                        rune=name,
                        previous_count=(
                            old['occurrence_count']
                        ),
                        occurrence_count=(
                            new['occurrence_count']
                        )
                    ))

        frames[step] = current
        previous = current

    return dict(
        profile_sha256=PROFILE_SHA256,
        casting_size=n,
        casting=casting,
        candidates=by_id,
        frames=frames,
        events=events,
        first_shown=first_shown,
        final=frames[n]
    )


# Authoritative configuration: the exact validated bytes supplied by the owner.
from pathlib import Path
import hashlib
import json
_PROFILE_DIR = Path(__file__).resolve().parent
_PROFILE_BYTES = (_PROFILE_DIR / 'rune_recognition_rc1.json').read_bytes()
PROFILE_SHA256 = hashlib.sha256(_PROFILE_BYTES).hexdigest()
if PROFILE_SHA256 != (_PROFILE_DIR / 'rune_recognition_rc1.sha256').read_text().strip():
    raise RuntimeError('Recognition profile checksum mismatch')
APPROVED_PROFILE = json.loads(_PROFILE_BYTES)
GRAMMAR = APPROVED_PROFILE['grammar']
BOLD_GEOMETRY = dict(APPROVED_PROFILE['geometry'])
BOLD_CHEVRONS = dict(APPROVED_PROFILE['chevrons'])
BOLD_FAMILY = dict(APPROVED_PROFILE['family'])
ENCLOSURE = dict(APPROVED_PROFILE['enclosure'])
BOLD_FORK = dict(APPROVED_PROFILE['fork'])
PAIRED = dict(APPROVED_PROFILE['paired'])
FINAL_RULES = dict(APPROVED_PROFILE['final'])
_P = APPROVED_PROFILE['presentation']
BOLD_MIN_SIZE = _P['min_size']
BOLD_IDEAL_MAX = _P['preferred_max']
BOLD_TARGET = _P['target_size']
BOLD_MIN_STROKE = _P['min_stroke']
BOLD_SIZE_FALLOFF = _P['size_falloff']
QUALITY_POWER = _P['quality_power']
DUP_ABS = _P['duplicate_absolute']
DUP_REL = _P['duplicate_relative']
CAL_QUALITY = dict(_P['quality_floors'])
APPROVED_QUALITY = dict(CAL_QUALITY)
CAL_NAMES = [r['name'] for r in GRAMMAR['runes']]
# Legacy notebook functions bind these defaults at definition time; values in RC1
# are exactly the same except where explicitly supplied by the calibrated path.
detect = detect_calibration
