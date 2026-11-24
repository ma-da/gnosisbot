/* Gnosis Financials — administrative cash register & service-credit reference valuation.
   Stripe reporting reads only on explicit request; no payments or blockchain operations. */
const $ = id => document.getElementById(id);
const money = cents => Number.isFinite(cents) ? new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100) : '—';
const today = () => new Date().toLocaleDateString('en-CA',{timeZone:'America/Chicago'});
const el = (tag,text,klass) => {const x=document.createElement(tag);if(text!==undefined&&text!==null)x.textContent=String(text);if(klass)x.className=klass;return x;};
let model=null;
let connections={};
let stripeConnection={configured:false};
function status(t,bad=false){const n=$('finance-status');if(n){n.textContent=t;n.dataset.error=String(bad);}}
async function api(path,opts={}){
 const r=await fetch('/api/v1/admin/finance'+path,{credentials:'same-origin',cache:'no-store',...opts});
 if(!r.ok){let msg=`Financial API error (${r.status})`;try{const b=await r.json();if(typeof b.detail==='string')msg=b.detail;}catch{}throw new Error(msg);}
 return r.json();
}
function save(path,method,obj){return api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)});}
function metric(label,value,sub){const d=el('div',null,'finance-metric');d.append(el('span',label),el('strong',value),el('small',sub));return d;}
function editButton(label,cb){const b=el('button',label,'secondary finance-quiet');b.type='button';b.addEventListener('click',cb);return b;}
function tableCell(r,text){const td=el('td',text);r.append(td);return td;}
function formValue(form,name){return form.elements.namedItem(name)?.value ?? '';}
function financeAmount(s){const v=String(s).trim();if(!/^\d+(?:\.\d{1,2})?$/.test(v))throw new Error('Enter a nonnegative USD amount, at most two decimals');return Math.round(Number(v)*100);}
function render(){if(!model)return;
 const s=model, stripe=s.stripe;const sm=$('financials');sm.replaceChildren(
   metric('Project net + provider value',money(s.project_known_net_cents),s.valuation_complete?'Calculated from entered figures':'PROVISIONAL · missing inputs'),
   metric('Stripe net receipts',money(stripe.net_cents),stripe.as_of?`Through ${stripe.as_of} · ${stripe.source}`:'Not connected; no assumed revenue'),
   metric('Monthly overhead',money(s.monthly_current_cents),'Current scheduled run rate'),
   metric('Costs since Oct 1',money(s.total_incurred_cost_cents),'Scheduled recurring + incurred one-time'),
   metric('Known provider value',money(s.provider_known_value_cents),'Noncash replacement-value estimate'),
   metric('Cash net',s.cash_complete?money(s.cash_known_net_cents):'—','Excludes noncash provider credits')
 );
 const note=$('finance-quality');note.textContent=s.missing.length?`Missing / provisional: ${s.missing.join(' · ')}`:'Reported inputs complete. Monetary figures depend on entered source data.';
 $('finance-period').textContent=`Project start ${s.project_start} · through ${s.as_of}`;
 const tbody=$('finance-item-rows');tbody.replaceChildren();
 for(const item of s.items){const tr=el('tr');tableCell(tr,item.name);tableCell(tr,({monthly_cost:'Monthly expense',one_time_cost:'One-time expense',revenue:'Other revenue',monthly_revenue:'Monthly revenue'})[item.kind]);tableCell(tr,money(item.amount_cents));tableCell(tr,item.status);tableCell(tr,['monthly_cost','monthly_revenue'].includes(item.kind)?item.starts_on+(item.ends_on?` – ${item.ends_on}`:' onward'):(item.occurs_on||'Unscheduled'));
  const act=el('td');act.append(editButton('Edit',()=>openItem(item)),editButton('Remove',()=>removeItem(item)));tr.append(act);tbody.append(tr);}
 const pbody=$('finance-provider-rows');pbody.replaceChildren();
 for(const p of s.providers){const tr=el('tr');tableCell(tr,p.name+(p.automatic?' · linked':''));tableCell(tr,p.quantity===null?'—':`${p.quantity} ${p.units}`);tableCell(tr,p.rate_usd===null?'—':`$${p.rate_usd} / ${p.units}`);tableCell(tr,money(p.valuation_cents));tableCell(tr,(p.state||'unknown')+(p.observed_at?' · '+p.observed_at:'')+(p.stale?' · stale':''));
  const act=el('td');if(!p.automatic){
    act.append(editButton('Edit',()=>openProvider(p)));
    if(['deepseek','deepinfra'].includes(p.provider_id)){
      if(connections[p.provider_id]?.configured){act.append(editButton('Sync balance',()=>syncProvider(p)));}
      else act.append(el('small','API key not configured'));
    }else if(p.provider_id==='ankr'){act.append(el('small','Account OAuth needed for balance'));}
    else if(p.provider_id==='iqm'){act.append(el('small','Resonance balance: manual'));}
    act.append(editButton('Remove',()=>removeProvider(p)));
  }tr.append(act);pbody.append(tr);}
 const wallet=s.settings;$('finance-wallet-address').textContent=wallet.solana_address||'Not configured';$('finance-wallet-mint').textContent=wallet.rstory_mint||'Not configured';
 $('finance-wallet-form').elements.namedItem('solana_address').value=wallet.solana_address||'';
 $('finance-wallet-form').elements.namedItem('rstory_mint').value=wallet.rstory_mint||'';
 if(stripe.as_of){const f=$('finance-stripe-form');for(const n of ['gross','fees','refunds'])f.elements.namedItem(n).value=(stripe[n+'_cents']/100).toFixed(2);f.elements.namedItem('as_of').value=stripe.as_of;f.elements.namedItem('source').value=stripe.source||'';}
 $('finance-stripe-state').textContent=stripe.as_of?`Snapshot as of ${stripe.as_of}. Gross ${money(stripe.gross_cents)} − fees ${money(stripe.fees_cents)} − refunds ${money(stripe.refunds_cents)} = ${money(stripe.net_cents)}.`:'Stripe integration inactive. You may enter a cumulative manual snapshot from Oct 1.';
}
async function load(){try{const [data,info,stripeInfo]=await Promise.all([api(''),api('/connections'),api('/stripe/connection')]);model=data;connections=info.providers||{};stripeConnection=stripeInfo;render();updateStripeControl();status('Financials updated · '+model.as_of);}catch(e){status(e.message,true);}}
async function syncProvider(p){
 status(`Reading ${p.name} balance…`);
 try{
  await api('/providers/'+encodeURIComponent(p.provider_id)+'/refresh',{method:'POST'});
  await load();
  status(`${p.name} balance refreshed from provider; other items unchanged.`);
 }catch(e){status(e.message||'Balance refresh failed',true);}
}
// Explicit admin-only Stripe reporting. Never called during initial page load.
function updateStripeControl(){
 const anchor=$('finance-stripe-state');if(!anchor)return;
 let button=$('finance-stripe-sync');
 if(!button){button=editButton('Sync Stripe receipts',()=>void syncStripe());button.id='finance-stripe-sync';anchor.after(button);}
 const enabled=Boolean(stripeConnection.configured && stripeConnection.live_restricted_key);
 button.hidden=!enabled;
 if(!enabled)anchor.textContent += ' · Automatic reporting requires a live restricted reporting key.';
}
async function syncStripe(){
 if(!window.confirm('Read cumulative Stripe transactions since October 1, 2026 and replace the current Stripe summary? This does not create payments or issue credits.'))return;
 const button=$('finance-stripe-sync');if(button)button.disabled=true;
 status('Reading Stripe transactions (read-only)…');
 try{await api('/stripe/refresh',{method:'POST'});await load();status('Stripe reporting refreshed successfully; no payments created.');}
 catch(e){status(e.message||'Stripe reporting unavailable',true);}
 finally{if(button)button.disabled=false;}
}
function openItem(item){const f=$('finance-item-form');f.reset();f.dataset.id=item?.item_id||'';
 $('finance-item-title').textContent=item?'Edit financial item':'Add financial item';
 const values=item||{name:'',category:'General',kind:'monthly_cost',amount_cents:0,status:'active',starts_on:'2026-10-01',ends_on:'',occurs_on:'',memo:''};
 for(const k of ['name','category','kind','status','starts_on','ends_on','occurs_on','memo'])f.elements.namedItem(k).value=values[k]||'';
 f.elements.namedItem('amount').value=(values.amount_cents/100).toFixed(2);syncItemStatus();$('finance-item-dialog').showModal();}
function syncItemStatus(){const f=$('finance-item-form'),k=formValue(f,'kind'),s=f.elements.namedItem('status'),value=s.value;
 const options={monthly_cost:[['active','Active'],['planned','Planned'],['disabled','Disabled']],monthly_revenue:[['active','Active'],['planned','Planned'],['disabled','Disabled']],one_time_cost:[['planned','Planned'],['incurred','Incurred'],['disabled','Disabled']],revenue:[['planned','Planned'],['received','Received'],['disabled','Disabled']]};
 s.replaceChildren(...options[k].map(([v,t])=>{const o=el('option',t);o.value=v;return o;}));s.value=options[k].some(x=>x[0]===value)?value:options[k][0][0];
 $('finance-monthly-fields').hidden=!['monthly_cost','monthly_revenue'].includes(k);$('finance-occurs-fields').hidden=['monthly_cost','monthly_revenue'].includes(k);
}
async function removeItem(item){if(!window.confirm(`Remove ${item.name} from financial reporting? The action remains auditable.`))return;try{await api('/items/'+encodeURIComponent(item.item_id),{method:'DELETE'});await load();}catch(e){status(e.message,true);}}
function openProvider(p){const f=$('finance-provider-form');f.reset();const x=p||{provider_id:'',name:'',units:'USD',quantity:'',rate_usd:'1',state:'unknown',source:'operator',observed_at:'',notes:''};
 for(const k of ['provider_id','name','units','quantity','rate_usd','state','source','observed_at','notes'])f.elements.namedItem(k).value=x[k]??'';
 f.elements.namedItem('provider_id').readOnly=Boolean(p);
 $('finance-provider-title').textContent=p?'Edit provider balance':'Add provider balance';$('finance-provider-dialog').showModal();}
async function removeProvider(p){if(!window.confirm(`Remove ${p.name} from provider valuations?`))return;try{await api('/providers/'+encodeURIComponent(p.provider_id),{method:'DELETE'});await load();}catch(e){status(e.message,true);}}
$('finance-new-item')?.addEventListener('click',()=>openItem());
$('finance-new-provider')?.addEventListener('click',()=>openProvider());
$('finance-item-form')?.elements.namedItem('kind').addEventListener('change',syncItemStatus);
$('finance-item-cancel')?.addEventListener('click',()=>$('finance-item-dialog').close());
$('finance-provider-cancel')?.addEventListener('click',()=>$('finance-provider-dialog').close());
$('finance-item-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector('[type="submit"]');b.disabled=true;try{
  const obj={name:formValue(f,'name'),category:formValue(f,'category'),kind:formValue(f,'kind'),status:formValue(f,'status'),amount_cents:financeAmount(formValue(f,'amount')),starts_on:formValue(f,'starts_on')||null,ends_on:formValue(f,'ends_on')||null,occurs_on:formValue(f,'occurs_on')||null,memo:formValue(f,'memo')};
  const id=f.dataset.id;await save(id?'/items/'+encodeURIComponent(id):'/items',id?'PUT':'POST',obj);$('finance-item-dialog').close();await load();
 }catch(err){status(err.message,true);}finally{b.disabled=false;}});
$('finance-provider-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector('[type="submit"]');b.disabled=true;try{
 const obj={};for(const k of ['provider_id','name','units','quantity','rate_usd','state','source','observed_at','notes'])obj[k]=formValue(f,k);
 await save('/providers/'+encodeURIComponent(obj.provider_id),'PUT',obj);$('finance-provider-dialog').close();await load();
 }catch(err){status(err.message,true);}finally{b.disabled=false;}});
$('finance-stripe-form')?.addEventListener('submit',async e=>{e.preventDefault();if(!window.confirm('Replace the cumulative Stripe manual snapshot? Do not enter amounts already included in Other revenue.'))return;
 const f=e.currentTarget,b=f.querySelector('[type="submit"]');b.disabled=true;try{
 const obj={gross_cents:financeAmount(formValue(f,'gross')),fees_cents:financeAmount(formValue(f,'fees')),refunds_cents:financeAmount(formValue(f,'refunds')),as_of:formValue(f,'as_of'),source:formValue(f,'source')};await save('/stripe','PUT',obj);await load();
 }catch(err){status(err.message,true);}finally{b.disabled=false;}});
$('finance-wallet-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector('[type="submit"]');b.disabled=true;try{
 await save('/wallet','PUT',{solana_address:formValue(f,'solana_address'),rstory_mint:formValue(f,'rstory_mint')});await load();
 }catch(err){status(err.message,true);}finally{b.disabled=false;}});
$('finance-refresh')?.addEventListener('click',()=>void load());
$('refresh')?.addEventListener('click',()=>void load());
$('finance-audit-button')?.addEventListener('click',async()=>{try{const data=await api('/audit');const n=$('finance-audit');n.replaceChildren();for(const r of data.records){n.append(el('p',`${r.at} · ${r.action} · ${r.entity_id.slice(0,20)} · actor ${r.actor.slice(0,12)}`));}if(!data.records.length)n.textContent='No changes recorded yet.';}catch(e){status(e.message,true);}});
void load();
