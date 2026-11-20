/* Gnosis Elder Futhark — M5B consultation client. No entropy, ledger or signing logic.
 * Source availability and prices are server-owned. Replay never submits a cast. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ROOT = '/api/v1/consultations';
  const ID = /^[0-9a-f]{32}$/;
  const specifications = [
    ['classic', 'Classic', 'Server cryptographic randomness', 'classic'],
    ['qrng_private', 'QCI Quantum Noise', 'Optical quantum randomness', 'qci'],
    ['qrng_public', 'NIST Public Beacon', 'Public randomness, deterministically derived', 'nist'],
    ['quantum_past', 'IBM Quantum Past', 'Archived hardware measurements', 'ibm_qpu'],
    ['quantum_future', 'IBM Quantum Future', 'New hardware execution', 'ibm_qpu']
  ];
  const safeId = id => typeof id === 'string' && ID.test(id);
  const serviceId = (mode, key) => `runes.${mode}.${key}`;
  const terminal = ['failed', 'cancelled', 'canceled'];
  const pending = ['pending', 'queued', 'submitting', 'submitted', 'running', 'verifying', 'needs_review'];
  const marker = 'gnosis.runes.unresolved.v1';
  function markerRead() { try { return sessionStorage.getItem(marker); } catch { return null; } }
  function markerWrite(value) { try { if (value) sessionStorage.setItem(marker, value); else sessionStorage.removeItem(marker); } catch {} }
  async function request(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options, signal: AbortSignal.timeout(options.method === 'POST' ? 120000 : 15000)});
    const body = await response.json().catch(() => null);
    return {code: response.status, ok: response.ok, body};
  }
  function messageFrom(r) {
    const detail = r.body?.detail;
    if (r.code === 401) return 'Sign in through Your Gnosis before casting.';
    if (r.code === 402) return 'Insufficient available credits. Check Your Gnosis.';
    if (r.code === 403) return 'Request origin rejected. Open Gnosis directly.';
    if (r.code === 404) return 'Reading not found or not available to this account.';
    if (r.code === 429) return `Cooldown active.${detail?.next_eligible_at ? ' Next eligible: ' + detail.next_eligible_at : ' Try again later.'}`;
    if (r.code === 503) return 'Selected source is unavailable. No substitute source was used.';
    return typeof detail?.message === 'string' ? detail.message : `Request returned HTTP ${r.code}.`;
  }
  function checkEnvelope(d, id, expected) {
    if (!d || d.schema_version !== 'rune-reading-v0' || d.reading_id !== id || !safeId(id) || d.status !== 'ready' || !['pouch','sticks'].includes(d.mode)) throw Error('Incompatible saved rune reading.');
    const spec = expected ? specifications.find(x => serviceId(d.mode,x[0]) === expected) : null;
    if (expected && (!spec || spec[3] !== d.source || d.delivery !== (spec[0] === 'quantum_past' ? 'precomputed' : 'live'))) throw Error('Receipt source or delivery does not match the requested service.');
    if (!((['classic','qci','nist'].includes(d.source) && d.delivery === 'live') || (d.source === 'ibm_qpu' && ['live','precomputed'].includes(d.delivery)))) throw Error('A live reading cannot be a demonstration or an unknown source.');
    return d;
  }
  function init({showReading, onMode, onPending, onFailure, initialMode = 'sticks'}) {
    const dialog = $('rune-consultation'), form = $('rune-consultation-form');
    const sources = $('rune-service-options'), submit = $('rune-submit'), close = $('rune-close');
    const note = $('rune-consultation-message'), balance = $('rune-balance'), inventory = $('rune-inventory-status');
    const status = $('rune-production-status'), retry = $('rune-status-retry');
    let mode = initialMode, selected = 'classic', qrngChoice = 'qrng_private', catalog = [], account = null, refreshing = false;
    let serial = 0, busy = false, attempt = null, receiptId = null, expected = null, poll = null, polling = false, backoff = 4000, locked = !!markerRead();
    let inventoryModule = null, refreshInventory = null; let pausedPolling=false;
    // All UI selections resolve to one of the original ten authoritative service IDs.
    const service = key => catalog.find(x => x.service_id === serviceId(mode,key) && x.application_id === 'runes' && x.mode === mode);
    const entry = () => service(selected);
    const quantum = key => key === 'qrng_private' || key === 'qrng_public';
    const group = () => quantum(selected) ? 'qrng' : selected;
    const checkMode = () => { for (const r of form.querySelectorAll('[name="rune-method"]')) r.checked = r.value === mode; };
    const availableBalance = () => account?.available ?? account?.credits;
    const validPrice = s => s && Number.isInteger(s.credits) && s.credits >= 0 && Number.isInteger(s.min_balance) && s.min_balance >= 0 && s.price_provisional === false;
    const admitted = s => validPrice(s) && s.available === true;
    const enough = s => Number.isFinite(availableBalance()) && availableBalance() >= Math.max(s.credits,s.min_balance);
    const setNote = text => {note.textContent=text;note.hidden=!text;};
    function setStatus(text, retryLabel = '') {
      status.hidden = !text; $('rune-production-message').textContent = text;
      retry.hidden = !retryLabel; retry.textContent = retryLabel;
    }
    function setQuery(id) { const url = new URL(location.href); url.search = ''; url.searchParams.set('reading',id); history.replaceState(null,'',url); }
    // Shared I Ching presentation; rune admission remains catalog-driven.
    const labels = {classic:'Consult the Oracle', qrng:'Sample Quantum Noise', quantum_past:'Draw From the IBM Archive', quantum_future:'Measure the Qubits'};
    const groups = [['classic','System Random','system'],['qrng','Quantum Randomness','quantum'],['quantum_past','True Quantum Past','past'],['quantum_future','True Quantum Future','future']];
    const providers = ['qrng_private','qrng_public'];
    const groupEnabled = key => key === 'qrng' ? providers.some(p => admitted(service(p))) : admitted(service(key));
    function priceText(item) {
      if (item?.price_provisional) return 'Provisional price · unavailable';
      if (!validPrice(item)) return 'Unavailable';
      return `${item.credits} credits${item.min_balance > item.credits ? ' · balance ≥'+item.min_balance : ''}${item.available !== true ? ' · unavailable' : ''}`;
    }
    function sync() {
      const s = entry(), frozen = busy || !!attempt;
      submit.disabled = busy || refreshing || !!receiptId || (locked && !attempt) || (!attempt && (!account || !admitted(s) || !enough(s)));
      submit.textContent = attempt ? 'Retry same consultation' : labels[group()];
      close.disabled = busy;
      for (const input of form.querySelectorAll('input,textarea,select')) {
        input.disabled = frozen || (input.name === 'rune-source' && !groupEnabled(input.value)) || (input.name === 'rune-provider' && !admitted(service(input.value)));
        if (input.name === 'rune-source') input.checked = input.value === group();
        if (input.name === 'rune-provider') input.checked = input.value === qrngChoice;
      }
      checkMode();
      $('rune-dialog-mode').disabled = frozen;
      $('rune-qrng').hidden = !quantum(selected);
      const providerCopy = qrngChoice === 'qrng_private' ? 'Private optical quantum randomness.' : 'Public, timestamped beacon; deterministic derivation.';
      $('rune-provider-detail').textContent = `${providerCopy} ${priceText(service(qrngChoice))}.`;
      const required = validPrice(s) ? Math.max(s.credits,s.min_balance) : null;
      $('rune-cost').textContent = required === null ? 'Price unavailable' : `${s.credits} credits${required > s.credits ? ' · balance ≥'+required+' required' : ''}${s.async_job ? ' · asynchronous' : ''}`;
      balance.textContent = account ? `Signed in · ${availableBalance()} available credits${s && admitted(s) && !enough(s) ? ' · insufficient balance' : ''}` : 'Sign in through Your Gnosis';
      balance.dataset.status = account ? (s && admitted(s) && !enough(s) ? 'error' : 'verified') : 'neutral';
      $('rune-login-link').hidden = !!account;
      if (refreshInventory) Promise.resolve(refreshInventory()).catch(()=>{});
    }
    function renderOptions() {
      sources.replaceChildren();
      for (const [key,label,area] of groups) {
        const wrap=document.createElement('label'); wrap.className='consultation-mode'; wrap.style.setProperty('--mode-area',area);
        const radio=document.createElement('input'); radio.type='radio'; radio.name='rune-source'; radio.value=key;
        const title=document.createElement('span'); title.className='consultation-mode-name'; title.textContent=label;
        const cost=document.createElement('span'); cost.className='consultation-mode-cost';
        const item = service(key);
        if (key==='qrng') {
          const offered=providers.filter(p=>admitted(service(p)));
          const prices=offered.map(p=>priceText(service(p)));
          cost.textContent = offered.length ? ([...new Set(prices)].length===1 ? prices[0] : 'Provider-specific cost') : 'Unavailable';
        } else {
          cost.textContent=priceText(item)+(key==='classic' && admitted(item) ? ' · server' : key==='quantum_past' ? ' · archived IBM' : key==='quantum_future' ? ' · new IBM job' : '');
        }
        wrap.append(radio,title,cost);
        if (key==='quantum_past') { const stock=document.createElement('span'); stock.id='rune-past-stock'; stock.className='consultation-mode-cost'; stock.textContent='Inventory status unavailable'; wrap.append(stock); }
        radio.onchange=()=>{
          if (busy || attempt || !groupEnabled(key)) return;
          if (key==='qrng') {
            // Choose an available provider only on explicit selection of the group.
            // Catalog refreshes never silently replace a previously selected source.
            if (!admitted(service(qrngChoice))) qrngChoice=providers.find(p=>admitted(service(p))) || qrngChoice;
            selected=qrngChoice;
          } else selected=key;
          sync();
        };
        sources.append(wrap);
      }
      sync();
    }
    for (const radio of form.querySelectorAll('[name="rune-provider"]')) radio.onchange=()=>{
      if (busy || attempt || !admitted(service(radio.value))) return;
      qrngChoice=radio.value; selected=qrngChoice; sync();
    };
    async function refresh() {
      const seq=++serial; refreshing=true; catalog=[];account=null;renderOptions();setNote('Checking account and sources…');
      try {
        const [a,c]=await Promise.all([request('/api/v1/accounts/me'),request('/api/v1/services/catalog')]);
        if(seq!==serial)return;
        if(c.ok && Array.isArray(c.body?.services)) catalog=c.body.services.filter(s=>s.application_id==='runes');
        if(a.ok && a.body?.account_id && Number.isFinite(a.body.available ?? a.body.credits))account=a.body;
        setNote(!c.ok || !Array.isArray(c.body?.services) ? 'Source catalog unavailable. No cast can be submitted.' : a.code===401 ? 'Sign in to make a reading, including Classic.' : !account ? 'Account status unavailable.' : '');
      } catch { if(seq===serial)setNote('Unable to check account or reading sources.'); }
      finally { if(seq===serial){refreshing=false;renderOptions();refreshPast(seq,mode);} }
    }
    async function refreshPast(seq, currentMode) {
      try {
        const m=inventoryModule || await import('/assets/js/inventory-status.js?v=1');
        inventoryModule=m;
        if(!refreshInventory){refreshInventory=m.createInventoryStatus({node:inventory,getServiceId:()=>serviceId(mode,selected)});refreshInventory();}
        const data=await m.fetchInventory();
        if(seq!==serial || currentMode!==mode || !dialog.open)return;
        const e=data.engines.find(x=>x.service_id===serviceId(mode,'quantum_past'));
        $('rune-past-stock').textContent=m.stockText(e);
      } catch { /* Optional inventory display never enables admission. */ }
    }
    function open(nextMode=mode) {
      if(receiptId){setStatus('A reading is still being processed. Check its status or Your Gnosis.', 'Check status');return;}
      if(locked && !attempt){setStatus('A previous request may have been interrupted. Check Your Gnosis before starting another reading.','');$('rune-unlock').hidden=false;return;}
      if(!attempt){mode=nextMode; checkMode();}
      if(!dialog.open)dialog.showModal();
      if(attempt){setNote('Outcome unknown. Retry sends the exact same request and key, not a new cast.');sync();}else refresh();
    }
    function unlock(){attempt=null;locked=false;markerWrite(null);$('rune-unlock').hidden=true;}
    function clearInquiry(){$('rune-question').value='';$('rune-consent').checked=false;}
    function resolveCurrent(id){if(attempt || markerRead()===`receipt:${id}`)unlock();}
    function finish(d,id,service){checkEnvelope(d,id,service);showReading(d);resolveCurrent(id);clearInquiry();receiptId=null;expected=null;clearTimeout(poll);setQuery(id);setStatus('');if(dialog.open)dialog.close();busy=false;sync();}
    function fail(text){resolveCurrent(receiptId);receiptId=null;expected=null;clearTimeout(poll);setStatus(text);onFailure(text);if(dialog.open)dialog.close();busy=false;sync();}
    function follow(id, service){pausedPolling=false;if(!safeId(id))throw Error('Invalid consultation receipt ID.');receiptId=id;expected=service;if(attempt){attempt=null;locked=true;markerWrite(`receipt:${id}`);clearInquiry();}$('rune-unlock').hidden=true;retry.onclick=checkStatus;setQuery(id);onPending();if(dialog.open)dialog.close();setStatus('Reading is being processed. No additional reading will be requested.','Check status');schedule(0);}
    function schedule(delay=backoff){clearTimeout(poll);if(receiptId && !document.hidden && !pausedPolling)poll=setTimeout(checkStatus,delay);}
    async function checkStatus(){if(!receiptId || polling || document.hidden)return;const id=receiptId;polling=true;pausedPolling=false;try{
      const r=await request(`${ROOT}/${id}`);if(id!==receiptId)return;
      if(!r.ok){setStatus(messageFrom(r),'Check status');if([401,404].includes(r.code)){clearTimeout(poll);pausedPolling=true;backoff=30000;if(r.code===404 && !locked){receiptId=null;setStatus(messageFrom(r));onFailure();}}backoff=Math.min(backoff*2,30000);return;}
      const data=r.body;
      if(data?.application_id!=='runes' || data.consultation_id!==id || (expected && data.service_id!==expected))throw Error('Unexpected consultation status.');
      expected=data.service_id;
      if(data.status==='completed'){finish(data.result?.reading,id,expected);return;}
      if(terminal.includes(data.status)){fail('Reading failed or was cancelled. See Your Gnosis for settlement details. No fallback was used.');return;}
      if(!pending.includes(data.status))throw Error('Unrecognized consultation status.');
      if(!locked){locked=true;markerWrite(`receipt:${id}`);}
      setStatus(`Reading status: ${data.status.replaceAll('_',' ')}. See Your Gnosis for account and credit details.`,'Check status');backoff=data.status==='needs_review'?30000:4000;
    }catch(e){setStatus('Unable to verify reading status. Check Your Gnosis or retry status.','Check status');backoff=Math.min(backoff*2,30000);}finally{polling=false;if(receiptId)schedule();}}
    async function loadSaved(id){if(!safeId(id)){setStatus('Invalid saved reading link.');onFailure();return;}receiptId=id;onPending();setStatus('Loading your saved reading…');try{
      const r=await request('/api/v1/accounts/readings/'+id);
      if(r.ok){if(r.body?.application_id!=='runes'||r.body.schema_version!=='rune-reading-v0')throw Error('Not an Elder Futhark receipt.');finish(r.body.reading,id,r.body.service_id);return;}
      if(r.code===404){follow(id,null);return;}
      setStatus(messageFrom(r),'Retry saved reading');retry.onclick=()=>loadSaved(id);
    }catch{setStatus('Unable to load saved reading. No new reading was requested.','Retry saved reading');retry.onclick=()=>loadSaved(id);}}
    async function send(event){event.preventDefault();if(busy||receiptId||refreshing)return;const s=entry();
      if(!attempt){if(locked||!account||!admitted(s)||!enough(s))return;
        const body={service_id:s.service_id,idempotency_key:crypto.randomUUID(),question:$('rune-question').value,inquiry_style:form.querySelector('[name="rune-style"]:checked').value,research_publication_consent:$('rune-consent').checked};
        attempt={body:JSON.stringify(body),service:s.service_id,key:body.idempotency_key,accountId:account.account_id,sent:false};locked=true;markerWrite(attempt.key);
      }
      busy=true;sync();setNote('Requesting your reading…');
      try {
        // Recheck identity before retry: a new cookie must not replay another account's request.
        const a=await request('/api/v1/accounts/me');if(!a.ok||a.body?.account_id!==attempt.accountId){setNote('Sign back into the original account before retrying.');return;}
        const previouslySent=attempt.sent; attempt.sent=true;
        const r=await request(ROOT,{method:'POST',headers:{'Content-Type':'application/json'},body:attempt.body});
        const data=r.body,id=data?.receipt?.consultation_id;
        if(r.code===200||r.code===202){if(!safeId(id)||data.receipt.application_id!=='runes'||data.receipt.service_id!==attempt.service)throw Error('Invalid consultation receipt.');
          if(r.code===200 && data.state==='completed'){finish(data.result?.reading,id,attempt.service);return;}
          if(r.code===202 && data.state==='pending'){retry.onclick=checkStatus;follow(id,attempt.service);return;}
          throw Error('Unexpected receipt state.');}
        if(r.code===502 && data?.detail?.code==='rune_reading_failed'){fail(messageFrom(r));return;}
        // Only explicit admission/validation rejection is known not to have allocated a reading.
        if(!previouslySent && [401,402,403,422,429,503].includes(r.code)){unlock();setNote(messageFrom(r));return;}
        setNote(`${messageFrom(r)} Outcome uncertain; retry the same request or inspect Your Gnosis.`);
      }catch(e){setNote('Outcome uncertain. Retry sends the exact same request and key. You can also inspect Your Gnosis.');}
      finally{busy=false;sync();}
    }
    form.onsubmit=send;
    close.onclick=()=>{if(!busy)dialog.close();};
    dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
    dialog.addEventListener('click',e=>{if(busy || e.target!==dialog)return;const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();});
    $('rune-dialog-mode').onchange=e=>{if(attempt || busy || e.target.name!=='rune-method')return;mode=e.target.value;onMode(mode);refresh();};
    $('rune-new-reading').onclick=()=>open(mode);
    retry.onclick=checkStatus;
    document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(poll);else if(receiptId)schedule(0);});
    window.addEventListener('focus',()=>{if(dialog.open&&!busy&&!attempt)refresh();});
    // On reload the private question is deliberately not recoverable. Explicitly resolve via account activity.
    if(locked && !location.search.includes('reading=')){const prior=markerRead();if(prior?.startsWith('receipt:') && safeId(prior.slice(8))){queueMicrotask(()=>loadSaved(prior.slice(8)));}else{setStatus('A previous request may have been interrupted. Check Your Gnosis for its outcome before unlocking new readings.');$('rune-unlock').hidden=false;}}
    $('rune-unlock').onclick=()=>{if(!attempt && !receiptId && confirm('Have you checked Your Gnosis and resolved the previous request? This does not cancel any server reading.')){unlock();$('rune-unlock').hidden=true;setStatus('');}};
    return {open,loadSaved,setMode(m){mode=m;},getMode:()=>mode};
  }
  window.GnosisRuneConsultation={init,checkEnvelope};
})();
