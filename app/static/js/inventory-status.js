/** Public inventory snapshots. No credentials or private reading data are needed. */
export async function fetchInventory() {
  const r = await fetch('/api/v1/transparency/inventory', {cache:'no-store', credentials:'omit'});
  if (!r.ok) throw new Error(`Inventory HTTP ${r.status}`);
  const d = await r.json();
  if (d.schema_version !== 'gnosis.public-inventory.v1' || !Array.isArray(d.engines)) throw new Error('Unknown inventory response');
  return d;
}
const nf = n => Number(n).toLocaleString('en-US');
export function stockText(entry) {
  if (!entry || !Number.isSafeInteger(entry.counts?.available)) return 'Inventory status unavailable';
  const c = entry.counts;
  const parts = [`${nf(c.available)} available now`];
  if (c.pending_release) parts.push(`${nf(c.pending_release)} committed · awaiting release`);
  if (!entry.service_enabled && c.approved_available) parts.push(`${nf(c.approved_available)} approved · service disabled`);
  return parts.join(' — ');
}
/** Call on open and every engine/source change. Stale requests cannot overwrite selection. */
export function createInventoryStatus({node, getServiceId, fetcher=fetchInventory}) {
  let seq=0;
  node.setAttribute('aria-live','polite');
  return async function refresh() {
    const serial=++seq, id=getServiceId();
    node.hidden=!id?.endsWith('.quantum_past');
    if(node.hidden){node.textContent='';return;}
    node.textContent='Checking archived readings…';
    try {
      const d=await fetcher();
      if(serial!==seq || getServiceId()!==id) return;
      node.textContent=stockText(d.engines.find(e=>e.service_id===id));
    } catch(e) {
      if(serial===seq && getServiceId()===id) node.textContent='Inventory status unavailable';
    }
  };
}
/** I Ching modal adapter: existing selection and submission logic remain authoritative. */
export function attachIchingInventory({dialog, form, price, mode}) {
  const node=document.createElement('div');
  node.id='consultation-inventory-status'; node.hidden=true;
  node.className='consultation-inventory-status';
  node.style.marginTop='0.35rem';
  price.after(node);
  const refresh=createInventoryStatus({node,getServiceId:()=>mode()==='past'?'iching.quantum_past':null});
  const radio=form.querySelector('input[name="consultation-mode"][value="past"]');
  const note=document.createElement('small'); note.style.display='block';
  note.className='consultation-inventory-status'; note.setAttribute('aria-live','polite');
  // Also expose the stock summary beside the option, even when it is disabled.
  const label=radio?.closest('label');
  if(label){label.append(note);}
  let seq=0;
  async function opened(){
    const n=++seq;
    if(!dialog.open) return;
    void refresh();
    if(!label)return;
    note.textContent='Checking inventory…';
    try{const d=await fetchInventory();if(n===seq&&dialog.open)note.textContent=stockText(d.engines.find(e=>e.service_id==='iching.quantum_past'));}
    catch(e){if(n===seq&&dialog.open)note.textContent='Inventory status unavailable';}
  }
  form.addEventListener('change',e=>{if(e.target?.name==='consultation-mode')void refresh();});
  const observer=new MutationObserver(()=>{if(dialog.open)void opened();else ++seq;});
  observer.observe(dialog,{attributes:true,attributeFilter:['open']});
  if(dialog.open)void opened();
  return refresh;
}
