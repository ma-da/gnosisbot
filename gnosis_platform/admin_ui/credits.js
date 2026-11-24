/* Gnosis credit administration: no issue, grant, or redemption on page load. */
const $ = id => document.getElementById(id);
const val = n => n == null ? '—' : Number(n).toLocaleString(undefined,{maximumFractionDigits:1});
const node=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
async function api(path,options={}){const response=await fetch('/api/v1/admin/credits'+path,{credentials:'same-origin',cache:'no-store',...options});if(!response.ok){let detail='Request failed ('+response.status+')';try{const x=await response.json();if(typeof x.detail==='string')detail=x.detail;}catch{}throw Error(detail);}return response.json();}
const newKey=()=>crypto.randomUUID()+':'+crypto.randomUUID();
let lastData;
async function refresh(){try{
 const s=await api('/summary');lastData=s;
 $('credit-created').textContent=val(s.created);$('credit-destroyed').textContent=val(s.destroyed);$('credit-active').textContent=val(s.active);
 $('credit-unclaimed').textContent=val(s.unclaimed);$('credit-owned').textContent=val(s.accounts_active);
 $('credit-ibm-min').textContent=val(s.min_ibm_seconds);$('credit-replay-min').textContent=val(s.min_replay_inventory);
 $('credit-reconcile').textContent=s.reconciliation_difference===0?'Ledger reconciled':'WARNING: Supply difference '+s.reconciliation_difference;
 $('credit-reconcile').classList.toggle('credit-alert',s.reconciliation_difference!==0);
 $('credit-group-stats').replaceChildren(...s.groups.map(g=>node('div',`${g.group}: ${g.codes} codes · ${g.unclaimed} unclaimed · ${g.credits_unclaimed} credits unclaimed`)));
 // Only show shortfall if live and precisely comparable stock is known; never equate tracked IBM spent seconds with remaining instance budget.
 const overviewResponse=await fetch('/api/v1/admin/overview?days=30',{credentials:'same-origin',cache:'no-store'});
 if(overviewResponse.ok){const o=await overviewResponse.json();const instance=o.ibm?.instance||{};
 const remaining=instance.usage_remaining_seconds;
 const fresh=remaining!=null && Number.isFinite(Number(remaining)) && !instance.stale;
 $('credit-ibm-actual').textContent=fresh?'Actual: '+val(remaining)+' seconds':'Actual: unavailable or stale';
 $('credit-ibm-min').classList.toggle('credit-alert',fresh && Number(remaining)<s.min_ibm_seconds);
 // All three historical products back the shared replay reserve. Approved stock
 // stays counted during a temporary service outage; immediately serviceable
 // stock is shown separately. Missing engine data is UNKNOWN, never zero.
 const historicIds=['iching.quantum_past','runes.pouch.quantum_past','runes.sticks.quantum_past'];
 const engines=o.inventory?.engines||[];
 const historical=historicIds.map(id=>engines.find(x=>x.service_id===id));
 const countValid=(entry,key)=>entry && Number.isSafeInteger(entry.counts?.[key]) && entry.counts[key]>=0;
 const approvedKnown=historical.every(e=>countValid(e,'approved_available'));
 const availableKnown=historical.every(e=>countValid(e,'available'));
 const approved=approvedKnown?historical.reduce((n,e)=>n+e.counts.approved_available,0):null;
 const available=availableKnown?historical.reduce((n,e)=>n+e.counts.available,0):null;
 const output=$('credit-replay-actual');
 output.textContent=approvedKnown
   ?'Approved: '+val(approved)+' across I Ching + both Rune products'+
     (availableKnown?' · Serviceable now: '+val(available):' · Serviceable now: unknown')
   :'Approved inventory: unavailable or incomplete';
 // The backing reserve is physical released/approved unconsumed inventory,
 // not the current operational on/off switches for individual services.
 $('credit-replay-min').classList.toggle('credit-alert',approvedKnown && approved<s.min_replay_inventory);
 }else{$('credit-ibm-actual').textContent='Actual: unavailable';$('credit-replay-actual').textContent='Actual: unavailable';}
 const bs=await api('/batches');const target=$('credit-batches');target.replaceChildren(...bs.slice(0,12).map(b=>node('div',`${b.campaign_group} · ${b.redeemed}/${b.quantity} redeemed · ${b.credits_each} each · ${b.created_at.slice(0,10)}`)));
 $('credit-status').textContent='Supply updated';
 }catch(e){$('credit-status').textContent=e.message;}}
function exportCodes(result){if(!Array.isArray(result.codes)||!result.codes.length)return;
 const rows=['group,batch_id,claim_code,credits,expires_days',...result.codes.map(c=>[result.group,result.batch_id,c,result.credits_each,result.expires_days].join(','))];
 const blob=new Blob([rows.join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download='gnosis-claims-'+result.batch_id+'.csv';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
}
$('credit-issue-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget;
 const group=f.elements.group.value,quantity=Number(f.elements.quantity.value),credits_each=Number(f.elements.credits_each.value),expires_days=Number(f.elements.expires_days.value);
 if(!confirm(`Create ${quantity} ${group} claim codes, allocating ${quantity*credits_each} credits? Codes are downloadable only once.`))return;
 const button=f.querySelector('button[type=submit]');button.disabled=true;
 try{const result=await api('/batches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group,quantity,credits_each,expires_days,idempotency_key:newKey()})});
 if(result.already_created){$('credit-status').textContent=result.warning;}else{exportCodes(result);$('credit-status').textContent=`Allocated ${quantity*credits_each} credits. Store downloaded codes securely; no plaintext recovery.`;}await refresh();
 }catch(err){$('credit-status').textContent=err.message;}finally{button.disabled=false;}});
$('credit-refresh')?.addEventListener('click',refresh);
$('credit-report')?.addEventListener('click',async()=>{try{const rows=await api('/leaderboard');$('credit-report-output').replaceChildren(...rows.map(r=>node('div',`${r.account_id.slice(0,14)}… · ${r.credits_spent} credits spent · ${r.completed_charges} charges`)));}catch(e){$('credit-status').textContent=e.message;}});
$('credit-grant-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget;const account_id=f.elements.account_id.value.trim(),credits=Number(f.elements.credits.value),reason=f.elements.reason.value.trim();
 if(!confirm(`Grant ${credits} NEW credits to account ${account_id.slice(0,16)}…? Reason: ${reason}`))return;
 const button=f.querySelector('button[type=submit]');button.disabled=true;
 try{const result=await api('/grants',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id,credits,reason,idempotency_key:newKey()})});$('credit-status').textContent=result.created?'Credit grant created':'Grant already applied';f.reset();await refresh();}catch(err){$('credit-status').textContent=err.message;}finally{button.disabled=false;}});
refresh();
