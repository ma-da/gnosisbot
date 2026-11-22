const $=id=>document.getElementById(id);
const elem=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const fmt=(n,places=0)=>n===null||n===undefined?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:places});
const secs=n=>fmt(n,4);
const label=(s)=>{const parts=s.split('.');return (parts[0]==='iching'?'I Ching':parts[1]==='pouch'?'Rune Pouch':parts[1]==='sticks'?'Circular Sticks':parts[0])+' / '+({classic:'Classic',qrng_private:'QCI',qrng_public:'NIST',quantum_past:'IBM Past',quantum_future:'IBM Future'}[parts.at(-1)]||parts.at(-1));};
const state=s=>String(s||'unknown').replaceAll('_',' ');
const metric=(name,val,note)=>{const e=elem('div',undefined,'metric');e.append(elem('span',name),elem('strong',val));if(note)e.append(elem('p',note));return e;};
const row=(...fields)=>{const tr=elem('tr');for(const f of fields)tr.append(elem('td',String(f??'—')));return tr;};
const link=(label,url)=>{const a=elem('a',label);a.href=url;return a;};
let data,loading=false;
async function request(path,options={}){const r=await fetch(path,{credentials:'same-origin',cache:'no-store',...options});if(!r.ok){const e=new Error(r.status===401?'Sign in at the account page.':r.status===403?'Administrator access is required.':`Request unavailable (${r.status}).`);e.status=r.status;throw e;}return r.json();}
async function load(){if(loading)return;loading=true;$('refresh').disabled=true;$('status').textContent='Refreshing protected metrics…';try{data=await request('/api/v1/admin/overview?days='+encodeURIComponent($('days').value));render();$('dashboard').hidden=false;$('status').textContent='Updated '+data.as_of+' · Provider snapshots may be older.';}catch(e){$('dashboard').hidden=true;$('status').textContent=e.message;}finally{$('refresh').disabled=false;loading=false;}}
function render(){const inv=data.inventory.engines;const total=(k)=>inv.reduce((s,e)=>s+e.counts[k],0);$('summary').replaceChildren(metric('Completed readings',fmt(data.readings.total),'Saved genuine readings'),metric('Period readings',fmt(data.readings.period_total),'UTC selected period'),metric('Available stock',fmt(total('available')),`${fmt(total('pending_release'))} awaiting release`),metric('Commercial commitments',fmt(total('commercial')),`${fmt(total('delivered'))} delivered`),metric('Tracked IBM billed seconds',secs(data.ibm.totals.actual_seconds),`${data.ibm.totals.actual_known}/${data.ibm.totals.requests} jobs with final usage`));
const old=$('series').value;$('series').replaceChildren(elem('option','All reading types'));$('series').firstChild.value='all';for(const s of data.readings.series){const o=elem('option',label(s.service_id));o.value=s.service_id;$('series').append(o);}if([...$('series').options].some(o=>o.value===old))$('series').value=old;chart();$('reading-table').replaceChildren(...data.readings.series.map(s=>row(label(s.service_id),fmt(s.period_total),fmt(s.total))));
$('inventory').replaceChildren(...inv.map(e=>{const c=elem('article',undefined,'inventory-card');c.append(elem('h3',e.label),elem('strong',fmt(e.counts.available)),elem('p','Available now'));const dl=elem('dl');for(const [k,l] of Object.entries({commercial:'Commercial commitments',pending_release:'Awaiting release',reserved:'Reserved',delivered:'Delivered',demo:'Demo',excluded:'Excluded'}))dl.append(elem('dt',l),elem('dd',fmt(e.counts[k])));c.append(dl);const ul=elem('ul',undefined,'checks');for(const [k,l] of Object.entries({ibm_matched:'IBM match',committed:'Committed',signed:'Signed checkpoint',timestamp_submitted:'Timestamp submitted',bitcoin_verified:'Bitcoin release verification',released:'Released'})){const n=e.check_counts[k];ul.append(elem('li',`${n&&n===e.batch_count?'✓':'○'} ${l} (${n}/${e.batch_count})`,n&&n===e.batch_count?'check-ok':''));}c.append(ul,elem('p',e.service_enabled?'Service configured':'Service disabled','small'));return c;}));
const b=data.ibm;$('ibm-summary').replaceChildren(metric('Measured pre-overhead',secs(b.totals.measured_seconds),`${b.totals.measured_known}/${b.totals.requests} tracked jobs`),metric(`Planning +${b.overhead_seconds} s / request`,secs(b.totals.estimated_seconds),`${b.totals.estimate_known}/${b.totals.requests} jobs with baseline`),metric('Inventory billed s / reading',secs(b.inventory.actual_per_reading),'Amortized across commercial commitments'),metric('Future billed s / reading',secs(b.future.actual_per_reading),'Known final charges / completed readings'));$('ibm-groups').replaceChildren(...b.by_engine.map(g=>row(`${({iching:'I Ching',pouch:'Rune Pouch',sticks:'Circular Sticks'})[g.engine]} / ${g.kind}`,g.requests,g.commercial,secs(g.measured_seconds),secs(g.estimated_seconds),secs(g.actual_seconds),secs(g.estimated_per_reading),secs(g.actual_per_reading))));$('jobs').replaceChildren(...b.jobs.map(j=>row(j.job_id,`${j.engine} / ${j.kind}`,j.commercial,secs(j.measured_seconds),secs(j.planning_baseline_seconds),state(j.planning_basis),secs(j.estimated_seconds),secs(j.actual_seconds),fmt(j.resource_units,6))));$('jobs-note').textContent=b.jobs_truncated?'Showing 200 newest known jobs; aggregates include all tracked jobs.':'Only jobs attributed to Gnosis inventory and Future consultations are included.';
const i=b.instance, budget=b.budget;const age=o=>o.as_of?`${o.source||'Snapshot'} · ${o.as_of}${o.stale?' · stale':''}`:'Not configured / no provider snapshot';$('funding').replaceChildren(metric('Instance allocated / limit (s)',secs(i.usage_limit_seconds??i.usage_allocation_seconds),age(i)),metric('Instance usage (s)',secs(i.usage_consumed_seconds),i.instance_label||'Explicit instance required'),metric('Instance remaining (s)',secs(i.usage_remaining_seconds),age(i)),metric('Instance used (RU)',fmt(i.usage_consumed_ru,6),i.plan||'Provider plan'),metric('Instance limit (RU)',fmt(i.usage_limit_ru??i.usage_allocation_ru,6),age(i)),metric('Instance remaining (RU)',fmt(i.usage_remaining_ru,6),age(i)),metric('Budget limit (USD)',budget.limit_usd==null?'—':'$'+fmt(budget.limit_usd,2),age(budget)),metric('Spend (USD)',budget.spent_usd==null?'—':'$'+fmt(budget.spent_usd,2),age(budget)),metric('Budget remaining (USD)',budget.remaining_usd==null?'—':'$'+fmt(budget.remaining_usd,2),age(budget)));
$('checkpoints').replaceChildren(...data.checkpoints.map(c=>{const e=elem('article',undefined,'checkpoint');const a=elem('div');a.append(elem('strong',`Checkpoint ${c.tree_size}`),elem('p',`${c.released_batches} batch releases recorded`));const middle=elem('div');middle.append(elem('strong',state(c.status)),elem('p',c.block_heights.length?`Proof block heights: ${c.block_heights.join(', ')}`:'Block heights not yet checked'),elem('p',c.checked_at?`Checked ${c.checked_at}`:'No independent check recorded'));if(c.verification_method)middle.append(elem('p',`Verifier: ${state(c.verification_method)}`));const urls=elem('div');urls.append(link('Checkpoint file',`/api/v1/transparency/checkpoints/${c.tree_size}/file`));if(c.proof_sha256)urls.append(link('OTS proof',`/api/v1/transparency/checkpoints/${c.tree_size}/ots`));middle.append(urls);const button=elem('button','Verify BTC & release eligible stock');button.type='button';button.disabled=!c.proof_sha256;button.addEventListener('click',()=>verify(c.tree_size,button));e.append(a,middle,button);return e;}));
const contact=data.contacts;const stripe=data.stripe;
$('contact-legacy').replaceChildren(metric('Formspree submissions',fmt(contact.count),`${age(contact)}${contact.scope?' · '+contact.scope:''}`));
$('financials').replaceChildren(metric('Stripe gross revenue','—',state(stripe.status)),metric('Stripe net revenue','—','Payments not integrated'),metric('IBM billed seconds',secs(b.totals.actual_seconds),`${b.totals.actual_known}/${b.totals.requests} known final charges`),metric('IBM instance remaining (s)',secs(b.instance.usage_remaining_seconds),age(b.instance)));
const o=data.operations;$('operations').replaceChildren(metric('Database size',o.db_bytes==null?'—':fmt(o.db_bytes/1048576,2)+' MiB','Main SQLite file'),metric('Free storage',fmt(o.disk_free_bytes/1073741824,2)+' GiB',`${fmt(o.disk_total_bytes/1073741824,2)} GiB total`),metric('Unregistered readings',fmt(o.unregistered_completed),'Completed readings absent from ledger'));$('states').replaceChildren(...[['Consultations',o.consultations],['IBM jobs',o.ibm_jobs],['Notifications',o.notifications]].map(([name,values])=>elem('p',name+': '+(Object.entries(values).map(([k,v])=>state(k)+' '+v).join(' · ')||'No records'),'state-line')));}
async function verify(n,button){if(!window.confirm('This action verifies a Bitcoin proof and MAY RELEASE eligible committed quantum stock. Continue?'))return;button.disabled=true;$('proof-status').textContent=`Checking checkpoint ${n} against the configured verifier…`;try{const x=await request(`/api/v1/admin/transparency/${n}/check`,{method:'POST'});$('proof-status').textContent=`Checkpoint ${n}: ${state(x.status)}. ${x.inventory_changed?`${fmt(x.released_readings)} readings released across ${x.released_batches.length} batches.`:"No additional stock released."} ${x.verification_method?`(${state(x.verification_method)})`:""}`;await load();}catch(e){$('proof-status').textContent=e.message;}finally{button.disabled=false;}}
function chart(){if(!data)return;const rr=data.readings,selected=$('series').value;const vals=rr.dates.map((_,i)=>rr.series.filter(s=>selected==='all'||s.service_id===selected).reduce((sum,s)=>sum+s.daily[i],0));const total=vals.reduce((a,b)=>a+b,0);$('chart-summary').textContent=`${fmt(total)} readings during selected period`;const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 900 218');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${total} completed readings across ${vals.length} UTC days`);const add=(tag,attrs,text)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;};const top=18,bottom=180,left=42,right=880,peak=Math.max(1,...vals);for(let t=0;t<=4;t++){const y=bottom-(bottom-top)*t/4;add('line',{x1:left,y1:y,x2:right,y2:y,stroke:'#bcc5c5','stroke-width':'1.3'});add('text',{x:left-7,y:y+4,'text-anchor':'end','font-size':'11',fill:'#61797e'},(peak*t/4).toFixed(peak%4?1:0));}const w=(right-left)/vals.length;for(let i=0;i<vals.length;i++){const h=vals[i]/peak*(bottom-top);const rect=add('rect',{x:left+i*w,y:bottom-h,width:Math.max(.5,w*.76),height:h,fill:'#028090'});const title=document.createElementNS(ns,'title');title.textContent=`${rr.dates[i]}: ${vals[i]}`;rect.append(title);}const index=[...new Set([0,Math.floor((vals.length-1)/2),vals.length-1])];for(const i of index)add('text',{x:left+(i+.5)*w,y:204,'text-anchor':i===0?'start':i===vals.length-1?'end':'middle','font-size':'11',fill:'#61797e'},rr.dates[i]);$('chart').replaceChildren(svg);}
$('refresh').addEventListener('click',load);$('days').addEventListener('change',load);$('series').addEventListener('change',chart);load();

// Phase 1: admin-side mail composer is a visual preview; sending remains disabled.
const composer=$('mail-composer');
$('compose-open')?.addEventListener('click',()=>composer?.showModal());
$('compose-close')?.addEventListener('click',()=>composer?.close());

// Phase 2: encrypted native messages and manually gated email tools.
let contactOffset=0, contactBusy=false, currentSendEnabled=false;
const node=(tag,text,cls)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x;};
const mailStatus=s=>{$('mail-feedback').textContent=s;};

async function loadContacts({more=false}={}){
  if(contactBusy)return;contactBusy=true;
  if(!more){contactOffset=0;$('site-contact-list').replaceChildren();}
  $('contact-unread-status').textContent='Loading contact submissions…';
  try{
    const p=await request('/api/v1/admin/contact-messages?limit=50&offset='+contactOffset);
    if(!p.configured){
      $('contact-native-summary').textContent='Native site inbox: not enabled';
      $('contact-unread-count').textContent='— unread';
      $('contact-unread-status').textContent='Contact storage is disabled pending migration and activation; Formspree remains live.';
      $('site-contact-more').hidden=true;return;
    }
    $('contact-native-summary').textContent=`Native submissions: ${fmt(p.counts.total)} total · ${fmt(p.counts.unread)} unread`;
    $('contact-unread-count').textContent=`${fmt(p.counts.unread)} unread`;
    $('contact-unread-status').textContent=p.messages.length?'Unread items appear in black; use the controls to mark reviewed or archive.':'No messages in this page.';
    for(const message of p.messages){
      const item=node('details',undefined,'contact-message'+(!message.read_at&&!message.archived_at?' contact-message--unread':''));
      const head=node('summary');
      head.append(node('span',message.name),node('time',message.created_at.slice(0,16).replace('T',' ')+' UTC'));
      if(message.archived_at)head.append(node('span','Archived','contact-mini-tag'));
      item.append(head);
      const content=node('div',undefined,'contact-message-body');
      content.append(node('div',message.email,'contact-message-email'),node('p',message.message,'contact-message-text'));
      const actions=node('div',undefined,'action-row');
      const readButton=node('button',message.read_at?'Mark unread':'Mark read','secondary');
      readButton.type='button';
      readButton.addEventListener('click',async()=>{
        readButton.disabled=true;
        try{await request('/api/v1/admin/contact-messages/'+message.id+'/state',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:message.read_at?'mark_unread':'mark_read'})
        });await loadContacts();}catch(e){$('contact-unread-status').textContent=e.message;readButton.disabled=false;}
      });
      const archiveButton=node('button',message.archived_at?'Restore':'Archive','secondary');
      archiveButton.type='button';
      archiveButton.addEventListener('click',async()=>{
        archiveButton.disabled=true;
        try{await request('/api/v1/admin/contact-messages/'+message.id+'/state',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:message.archived_at?'restore':'archive'})
        });await loadContacts();}catch(e){$('contact-unread-status').textContent=e.message;archiveButton.disabled=false;}
      });
      const replyButton=node('button','Reply by email','secondary');replyButton.type='button';
      replyButton.addEventListener('click',()=>{
        composer.dataset.contactId=message.id;
        $('mail-to').value=message.email;
        $('mail-from').value='support@gnosis.bot';
        $('mail-subject').value='Re: Your message to Gnosis.bot';
        $('mail-message').value='';
        composer.showModal();
      });
      actions.append(readButton,archiveButton,replyButton);
      content.append(actions);item.append(content);$('site-contact-list').append(item);
    }
    contactOffset+=p.messages.length;
    $('site-contact-more').hidden=!p.has_more;
  }catch(e){$('contact-unread-status').textContent=e.message;$('site-contact-more').hidden=true;
  }finally{contactBusy=false;}
}

async function loadMailConfig(){
  try{
    const p=await request('/api/v1/admin/mail/config');
    currentSendEnabled=Boolean(p.sending_enabled);
    $('mail-send').disabled=!currentSendEnabled;
    mailStatus(currentSendEnabled?'Ready for manual sending. Confirm recipients before sending.':'Sending disabled until Resend admin access is verified and enabled.');
    $('incoming-status').textContent=p.incoming_enabled?'Click Check incoming mail to list the latest received messages.':'Incoming Resend retrieval is not configured.';
  }catch(e){currentSendEnabled=false;$('mail-send').disabled=true;mailStatus(e.message);}
}

$('site-contact-more')?.addEventListener('click',()=>loadContacts({more:true}));
$('refresh')?.addEventListener('click',()=>{loadContacts();loadMailConfig();});
$('compose-open')?.addEventListener('click',()=>{
  delete composer.dataset.contactId;
  $('mail-from').value='quantum@gnosis.bot';
  $('mail-to').value='';$('mail-subject').value='';$('mail-message').value='';
});
$('mail-send')?.addEventListener('click',async()=>{
  if(!currentSendEnabled)return;
  const p={from_address:$('mail-from').value.trim(),to_address:$('mail-to').value.trim(),
    subject:$('mail-subject').value.trim(),message:$('mail-message').value,
    contact_message_id:composer.dataset.contactId||null};
  if(!p.from_address||!p.to_address||!p.subject||!p.message.trim()){
    mailStatus('Complete all fields before sending.');return;
  }
  if(!window.confirm(`Send this email from ${p.from_address} to ${p.to_address}?`))return;
  $('mail-send').disabled=true;mailStatus('Submitting to Resend…');
  try{
    const result=await request('/api/v1/admin/mail/send',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
    mailStatus(result.status==='sent'?`Accepted by Resend (${result.provider_message_id}); delivery not yet confirmed.`:
      `Send outcome requires review (${result.mail_id}). Do not send again automatically.`);
    if(result.status==='sent'){$('mail-message').value='';delete composer.dataset.contactId;}
  }catch(e){mailStatus(e.message+' · If a send was attempted, check the audit before retrying.');
  }finally{$('mail-send').disabled=!currentSendEnabled;}
});

$('incoming-check')?.addEventListener('click',async()=>{
  $('incoming-disclosure').open=true;
  $('incoming-status').textContent='Checking Resend incoming mail…';
  $('incoming-list').replaceChildren();
  $('incoming-check').disabled=true;
  try{
    const response=await request('/api/v1/admin/mail/incoming?limit=30');
    if(!response.configured){$('incoming-status').textContent='Resend receiving and an inbound read key are not configured.';return;}
    $('incoming-status').textContent=`${response.messages.length} received emails from the current page (provider snapshot on request).`;
    for(const item of response.messages){
      const container=node('details',undefined,'contact-message');
      const summary=node('summary',`${item.subject||'(No subject)'} · ${item.from||'Unknown sender'} · ${(item.created_at||'').slice(0,16)}`);
      const content=node('div',undefined,'contact-message-body');
      const t=node('p','Recipient: '+(item.to||[]).join(', '));
      const body=node('p','Open to retrieve plain-text content.','contact-message-text');
      let fetched=false;
      container.addEventListener('toggle',async()=>{
        if(!container.open||fetched)return;fetched=true;
        try{const message=await request('/api/v1/admin/mail/incoming/'+encodeURIComponent(item.id));
          const m=message.messages?.[0];body.textContent=m?(m.text_available?m.text:'No plain-text body available; HTML not rendered.'):'Message not available for gnosis.bot';
        }catch(e){body.textContent=e.message;}
      });
      content.append(t,body);container.append(summary,content);$('incoming-list').append(container);
    }
  }catch(e){$('incoming-status').textContent=e.message;
  }finally{$('incoming-check').disabled=false;}
});

loadContacts();
loadMailConfig();
