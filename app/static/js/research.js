import {initResearchInventory} from './research-inventory.js?v=1';
initResearchInventory();
/** Gnosis Research Observatory: public aggregate data only; no tracking or external libraries. */
const $ = id => document.getElementById(id);
const nf = n => Number(n).toLocaleString('en-US');
const dayISO = d => d.toISOString().slice(0,10);
const today = () => { const d=new Date(); return new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate())); };
const addDays = (d,n) => new Date(d.getTime()+86400000*n);
const maskFromBits = bits => {
  if(!/^[01]{6}$/.test(bits)) throw Error('Bad hexagram catalog bit pattern');
  return [...bits].reduce((m,b,i)=>m|(Number(b)<<i),0);
};
const nameFor = h => h ? `${h.number} · ${h.title}` : 'Unknown';
const symbolFor = n => n ? String.fromCodePoint(0x4dc0+n-1) : '—';

/**
 * Draw a six-line hexagram from the existing authoritative catalog bits.
 * Catalog bits are bottom-first; the glyph is drawn top-first.
 * Using SVG rather than a Unicode glyph keeps line widths consistent across OSes.
 */
function matrixHexagram(bits){
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.classList.add('research-symbol');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  if(!/^[01]{6}$/.test(bits ?? '')) return svg;

  for(let row = 0; row < 6; row++){
    const y = 6 + row * 16;
    const yang = bits[5 - row] === '1';
    const spans = yang ? [[8, 84]] : [[8, 36], [56, 36]];
    for(const [x, width] of spans){
      const bar = document.createElementNS(NS, 'rect');
      bar.setAttribute('x', x);
      bar.setAttribute('y', y);
      bar.setAttribute('width', width);
      bar.setAttribute('height', 10);
      bar.setAttribute('rx', '0');
      svg.append(bar);
    }
  }
  return svg;
}

let catalog=[], byMask=new Map(),selected=0, state=null, request=0, allSources=[];
function params(){
  const p=new URLSearchParams();
  const source=$('source-filter').value;if(source)p.set('source',source);
  p.set('phase',$('phase-filter').value);p.set('moving',$('moving-filter').value);
  const mode=$('time-filter').value, end=addDays(today(),1);
  if(mode==='today'){p.set('start',dayISO(today()));p.set('end',dayISO(end));}
  else if(mode==='week'){p.set('start',dayISO(addDays(end,-7)));p.set('end',dayISO(end));}
  else if(mode==='month'){const t=today();p.set('start',dayISO(new Date(Date.UTC(t.getUTCFullYear(),t.getUTCMonth(),1))));p.set('end',dayISO(end));}
  else if(mode==='custom') {if($('date-start').value)p.set('start',$('date-start').value);if($('date-end').value)p.set('end',$('date-end').value);}
  return p;
}
async function api(url){const res=await fetch(url,{cache:'no-store'});if(!res.ok)throw Error(`Research API returned ${res.status}`);return res.json();}
function showError(error){$('research-error').textContent='Could not load research data: '+error.message;$('research-error').hidden=false;}
function populateSources(list){const node=$('source-filter'),v=node.value;node.replaceChildren(new Option('All available sources',''));
  for(const item of list)node.add(new Option(`${item.id} (${nf(item.count)})`,item.id));
  node.value=[...node.options].some(opt=>opt.value===v)?v:'';
}
/** Fixed count scale: one additional occurrence cannot lighten a glyph.
 *  The half-dark point is 8 appearances; ratio mode has a separate scale.
 *  Exact counts remain in tooltips, accessible names and the inspector.
 */
function drawMatrix(){
  const root = $('hexagram-matrix');
  const focused = root.contains(document.activeElement) ? document.activeElement.dataset.mask : null;
  const items = state.dist.hexagrams;
  const shade = $('shade-filter').value;
  root.replaceChildren();
  for(let low=0; low<8; low++) for(let up=0; up<8; up++){
    const mask = low | (up<<3), item = items[mask], h = byMask.get(mask);
    const value = shade === 'count' ? Math.max(0, item.count) : Math.max(0, item.ratio ?? 0);
    const level = value / (value + (shade === 'count' ? 8 : 1));
    const gray = Math.round(180 - 150 * level);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'research-tile';
    button.dataset.mask = mask;
    button.style.color = `rgb(${gray}, ${gray}, ${gray})`;
    button.setAttribute('aria-pressed', String(selected === mask));
    button.setAttribute('aria-label', `${nameFor(h)}, observed ${item.count}, expected ${item.expected.toFixed(2)}`);
    button.title = `${nameFor(h)} · ${item.count} observed · ${item.expected.toFixed(2)} expected`;
    const symbol = matrixHexagram(h?.bits);
    button.append(symbol);
    button.addEventListener('click', () => {
      void selectMask(mask);
      document.dispatchEvent(new CustomEvent('gnosis:research-hexagram-open',
        {detail: {hexagram: h, observation: item, mask}}));
    });
    root.append(button);
  }
  // Selection redraws the matrix; retain keyboard focus without scrolling.
  if(focused !== null && /^\d+$/.test(focused)) root.querySelector(`[data-mask="${focused}"]`)?.focus({preventScroll:true});
}
function drawBars(){const node=$('research-bars');node.replaceChildren();const sort=$('sort-filter').value;const items=[...state.dist.hexagrams];
  if(sort==='king')items.sort((a,b)=>(byMask.get(a.mask)?.number??99)-(byMask.get(b.mask)?.number??99));
  else if(sort==='least')items.sort((a,b)=>a.count-b.count||a.mask-b.mask);
  else if(sort==='deviation')items.sort((a,b)=>Math.abs(b.count-b.expected)-Math.abs(a.count-a.expected)||a.mask-b.mask);
  else items.sort((a,b)=>b.count-a.count||a.mask-b.mask);
  const max=Math.max(1,...items.map(x=>x.count),state.dist.total_readings/64)*1.1;
  for(const x of items){const h=byMask.get(x.mask);const row=document.createElement('button');row.type='button';row.className='research-bar-row';
    const title=document.createElement('span');title.textContent=`${symbolFor(h?.number)} #${h?.number??'?'}`;title.title=nameFor(h);
    const track=document.createElement('span');track.className='research-bar-track';
    const fill=document.createElement('span');fill.className='research-bar-fill';fill.style.width=`${(x.count/max*100).toFixed(2)}%`;
    const marker=document.createElement('span');marker.className='research-bar-marker';marker.style.left=`${(x.expected/max*100).toFixed(2)}%`;
    track.append(fill,marker);const count=document.createElement('span');count.className='research-bar-number';count.textContent=nf(x.count);
    row.title=`${nameFor(h)}: observed ${x.count}, expected ${x.expected.toFixed(1)}`;
    row.append(title,track,count);row.addEventListener('click',()=>{
      void selectMask(x.mask);
      document.dispatchEvent(new CustomEvent('gnosis:research-hexagram-open',
        {detail: {hexagram: h, observation: x, mask: x.mask}}));
    });node.append(row);
  }
}
function drawSummary(){const {dist,summary}=state;
  $('stat-total').textContent=nf(dist.total_readings);
  $('stat-expected').textContent=(dist.total_readings/64).toFixed(2);
  $('stat-moving').textContent=summary.moving_rate===null?'—':(summary.moving_rate*100).toFixed(1)+'%';
  const p=dist.goodness_of_fit;
  $('stat-p').textContent=p.test_applicable?(p.p_value<0.0001?'<0.0001':p.p_value.toFixed(4)):'Not enough data';
  $('stat-p').title=p.test_applicable?`χ² = ${p.chi_square.toFixed(2)}, df = 63; exploratory only`:'Requires at least five expected observations per hexagram (320 total readings)';
}
function drawMoving(){const node=$('moving-bars');node.replaceChildren();const data=state.summary.moving_count_distribution;
  const max=Math.max(1,...data.map(x=>x.observed),...data.map(x=>x.expected));
  for(const x of data){const row=document.createElement('div');row.className='research-moving-row';const label=document.createElement('span');label.textContent=x.moving_count+' moving';
    const track=document.createElement('div');track.className='research-bar-track';const fill=document.createElement('span');fill.className='research-bar-fill';fill.style.width=`${x.observed/max*100}%`;
    const expected=document.createElement('span');expected.className='research-bar-marker';expected.style.left=`${x.expected/max*100}%`;
    track.append(fill,expected);const text=document.createElement('span');text.textContent=`${nf(x.observed)} / ${x.expected.toFixed(1)}`;row.append(label,track,text);node.append(row);
  }
}
function drawTrend(data){const node=$('trend-chart');node.replaceChildren();const points=data.points;
  if(!points.length){node.textContent='No observations in this period.';return;}
  const NS='http://www.w3.org/2000/svg';const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 900 215');svg.setAttribute('aria-label','Observed reading counts (teal) versus expected counts (gray)');
  const create=(name,attrs={})=>{const e=document.createElementNS(NS,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));svg.append(e);return e;};
  const max=Math.max(1,...points.map(p=>Math.max(p.observed,p.expected??0)));const x=i=>55+(points.length===1?0:i*815/(points.length-1));const y=v=>175-v/max*145;
  for(let j=0;j<=4;j++){const val=max*j/4;create('line',{x1:55,y1:y(val),x2:870,y2:y(val),stroke:'#e2e9e8'});const t=create('text',{x:48,y:y(val)+4,'text-anchor':'end',fill:'#667b7d','font-size':11});t.textContent=val.toFixed(0);}
  const path=key=>points.map((p,i)=>(i?'L':'M')+x(i).toFixed(2)+' '+y(p[key]??0).toFixed(2)).join(' ');
  create('path',{d:path('expected'),fill:'none',stroke:'#87979b','stroke-width':2,'stroke-dasharray':'6 5'});
  create('path',{d:path('observed'),fill:'none',stroke:'#028090','stroke-width':3});
  for(const [i,p] of points.entries()){if(points.length>35 && i%Math.ceil(points.length/30)!==0)continue;
    const circle=create('circle',{cx:x(i),cy:y(p.observed),r:3,fill:'#028090'});const tip=document.createElementNS(NS,'title');tip.textContent=`${p.period}: ${p.observed} observed, ${(p.expected??0).toFixed(2)} expected, ${p.total} readings`;circle.append(tip);
  }
  const begin=create('text',{x:55,y:203,fill:'#668085','font-size':12});begin.textContent=points[0].period;
  const end=create('text',{x:870,y:203,'text-anchor':'end',fill:'#668085','font-size':12});end.textContent=points.at(-1).period;
  node.append(svg);
}
async function selectMask(mask){selected=mask;drawMatrix();const item=state.dist.hexagrams[mask],hex=byMask.get(mask);$('selected-description').textContent=nameFor(hex);
  const node=$('selected-stats');node.replaceChildren();
  for(const [label,value] of [['Observed',nf(item.count)],['Expected',item.expected.toFixed(2)],['Observed / expected',item.ratio===null?'—':item.ratio.toFixed(2)+'×']]){
    const box=document.createElement('div'),small=document.createElement('small'),strong=document.createElement('strong');small.textContent=label;strong.textContent=value;box.append(small,strong);node.append(box);
  }
  const seq=request;const p=params();p.set('mask',mask);p.set('grain',$('grain-filter').value);
  try{const data=await api('/api/v1/research/timeseries?'+p);if(seq===request&&mask===selected)drawTrend(data)}catch(e){if(seq===request)showError(e)}
}
async function refresh(){const seq=++request;const p=params();$('research-loading').hidden=false;$('research-error').hidden=true;
  try{const [dist,summary]=await Promise.all([api('/api/v1/research/hexagrams?'+p),api('/api/v1/research/summary?'+p)]);
    if(seq!==request)return;state={dist,summary};populateSources(allSources);drawSummary();drawMatrix();drawBars();drawMoving();
    if(!byMask.has(selected))selected=0;await selectMask(selected);
  }catch(error){if(seq===request)showError(error)}finally{if(seq===request)$('research-loading').hidden=true}
}
function init(){for(const id of ['time-filter','source-filter','phase-filter','moving-filter','date-start','date-end'])$(id).addEventListener('change',()=>{
    const custom=$('time-filter').value==='custom';$('start-holder').hidden=!custom;$('end-holder').hidden=!custom;void refresh();
  });
  $('shade-filter').addEventListener('change',()=>state&&drawMatrix());$('sort-filter').addEventListener('change',()=>state&&drawBars());
  $('grain-filter').addEventListener('change',()=>state&&selectMask(selected));
}
init();
try{
  const list=await api('/api/v1/hexagrams');
  if(!Array.isArray(list)||list.length!==64)throw Error('Expected complete hexagram catalog');
  catalog=list;byMask=new Map(list.map(item=>[maskFromBits(item.bits),item]));
  if(byMask.size!==64)throw Error('Hexagram bit patterns are not unique');
  const all = await api('/api/v1/research/summary');
  allSources = all.sources;
  await refresh();
}catch(error){$('research-loading').hidden=true;showError(error)}
