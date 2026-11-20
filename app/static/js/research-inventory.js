import {fetchInventory} from './inventory-status.js?v=1';
const stages=[['ibm_matched','IBM archive matched'],['committed','Inventory committed'],['signed','Signed checkpoint'],['timestamp_submitted','Timestamp proof submitted'],['bitcoin_verified','Bitcoin verification recorded'],['released','Released into inventory']];
const nf=n=>Number(n).toLocaleString('en-US');
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
export function renderInventory(root,data){
  root.replaceChildren();
  for(const engine of data.engines){
    const c=engine.counts, card=el('article',undefined,'inventory-card');
    card.append(el('h3',engine.label),el('strong',nf(c.available),'inventory-available'),el('span','Available now','inventory-label'));
    const dl=el('dl',undefined,'inventory-counts');
    for(const [label,value] of [['Commercial commitments',c.commercial],['Awaiting release',c.pending_release],['Approved / unallocated',c.approved_available],['Reserved',c.reserved],['Delivered',c.delivered],['Demo reserve',c.demo],['Excluded',c.excluded],['Other unavailable',c.unavailable]]){
      dl.append(el('dt',label),el('dd',nf(value)));
    }
    card.append(dl);
    if(!engine.service_enabled)card.append(el('p','Consultation service not enabled.','inventory-note'));
    const list=el('ul',undefined,'inventory-checks');list.setAttribute('aria-label',`${engine.label} verification milestones`);
    for(const [key,label] of stages){
      const n=engine.check_counts[key],total=engine.batch_count, pass=total>0&&n===total;
      const row=el('li',undefined,pass?'inventory-check complete':'inventory-check');
      const mark=el('span',pass?'✓':'○','inventory-check-mark');mark.setAttribute('aria-hidden','true');
      row.append(mark,el('span',`${label} · ${n}/${total} batches`),el('span',pass?'Complete':n?'Partial':total?'Pending':'No batches','inventory-check-state'));list.append(row);
    }
    card.append(list);
    if(engine.batches.length){const details=el('details');details.append(el('summary','Hardware batches and checkpoints'));
      for(const b of engine.batches){const line=el('p');line.append(document.createTextNode(`IBM ${b.ibm_job_id} · ${b.counts.commercial} commercial · ${b.status}`));
        if(b.signed_checkpoint!==null){const a=el('a',`Checkpoint ${b.signed_checkpoint}`);a.href=`/api/v1/transparency/checkpoints/${b.signed_checkpoint}/file`;line.append(document.createTextNode(' · '),a);}
        details.append(line);}
      card.append(details);}
    root.append(card);
  }
}
export function initResearchInventory(){
  const root=document.getElementById('research-inventory-cards'),status=document.getElementById('research-inventory-status'),button=document.getElementById('research-inventory-refresh');
  if(!root||!status||!button)return;
  let seq=0;
  async function refresh(){const serial=++seq;button.disabled=true;status.textContent='Loading live inventory…';root.replaceChildren();
    try{const d=await fetchInventory();if(serial!==seq)return;renderInventory(root,d);status.textContent=`Updated ${new Date(d.as_of).toLocaleString()} · ${d.latest_checkpoint===null?'No signed checkpoint':`Latest signed checkpoint: ${d.latest_checkpoint}`}`;}
    catch(e){if(serial===seq)status.textContent='Inventory status unavailable. Try refreshing.';}
    finally{if(serial===seq)button.disabled=false;}}
  button.addEventListener('click',refresh);void refresh();
}
