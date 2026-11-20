/* Private feedback. No localStorage, no new cast, no credit operation. */
const ns = 'http://www.w3.org/2000/svg';
const pending = new Map();
function svgPart(tag, attributes) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}
export function faceButton(item) {
  if (item.status !== 'completed' || typeof item.resonance?.resonated !== 'boolean' ||
      !/^[0-9a-f]{32}$/.test(item.consultation_id)) return null;
  const id = item.consultation_id;
  const wrap = document.createElement('span');
  wrap.className = 'gnosis-resonance';
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'gnosis-resonance-face';
  button.setAttribute('aria-label', 'This reading resonated with me');
  const svg = svgPart('svg', {viewBox:'0 0 24 24', fill:'none', stroke:'currentColor',
    'stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'});
  const mouth = svgPart('path',{});
  svg.append(svgPart('circle',{cx:12,cy:12,r:9.5}),
    svgPart('path',{d:'M8.5 9.2h.1 M15.4 9.2h.1','stroke-width':'2.5'}),mouth);
  button.append(svg);
  const note = document.createElement('span');
  note.className = 'gnosis-resonance-note'; note.setAttribute('role','status');
  wrap.append(button,note);
  let selected = item.resonance.resonated;
  function show(value) {
    selected=value;
    button.setAttribute('aria-pressed',String(value));
    button.title=value?'Reading marked as resonant — click to unmark':'Mark this reading as resonant';
    mouth.setAttribute('d',value?'M7.5 13.5 Q12 19 16.5 13.5':'M7.5 16 Q12 10.5 16.5 16');
  }
  show(selected);
  async function follow(request) {
    button.disabled=true;
    note.textContent='';
    try {show((await request).resonated);}
    catch {note.textContent='Could not save. Refresh to check, then retry.';}
    finally {button.disabled=false;}
  }
  if(pending.has(id)) void follow(pending.get(id));
  button.addEventListener('click',()=>{
    if(pending.has(id)) return;
    const desired=!selected;
    const request=(async()=>{
      const response=await fetch(`/api/v1/accounts/readings/${id}/resonance`,{
        method:'PUT',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({resonated:desired})});
      if(!response.ok)throw new Error('Feedback unavailable');
      const result=await response.json();
      if(typeof result.resonated!=='boolean')throw new Error('Invalid feedback response');
      return result;
    })();
    pending.set(id,request);
    void follow(request).finally(()=>{if(pending.get(id)===request)pending.delete(id);});
  });
  return wrap;
}
