/** Gnosis system health v2 — public, read-only status. */
const ENDPOINTS = {
  catalog: '/api/v1/services/catalog',
  inventory: '/api/v1/transparency/inventory',
  diagnostics: '/api/v1/system/status'
};
const ENGINES = [['iching','I Ching'], ['runes.pouch','Pouch'], ['runes.sticks','Sticks']];
let dialog, details, summary, requestInFlight = null;
function el(tag, className = '', content = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = content;
  return node;
}

function readableStatus(status) {
  const labels = {
    healthy: 'Operational',
    degraded: 'Degraded',
    unavailable: 'Unavailable',
    unknown: 'Not verified',
    disabled: 'Disabled',
    available: 'Available',
    client_check_required: 'Client check required'
  };
  return labels[status] || 'Unknown';
}

function statusRow(name, description, status, detail = '') {
  const row = el('div', 'health-row');
  const info = el('div', 'health-row-info');
  const nameEl = el('strong', '', name);
  const descriptionEl = el('span', '', description);

  info.append(nameEl, descriptionEl);

  const state = el('div', 'health-row-state');
  const indicator = el('span', `health-indicator health-${status}`);
  indicator.setAttribute('aria-hidden', 'true');

  const label = el('span', '', readableStatus(status));
  const statusLine = el('div', 'health-state-line');

  statusLine.append(indicator, label);
  state.append(statusLine);

  if (detail) {
    state.append(el('small', '', detail));
  }

  row.append(info, state);
  return row;
}

function formatDate(value) {
  if (!value) return 'Not checked';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Not checked'
    : date.toLocaleString();
}


// Public API availability is configuration/admission state, not proof of a live QPU or QRNG probe.
export function buildHealthView(catalog, inventory, diagnostics, browserCrypto, now = Date.now()) {
  const services = new Map((Array.isArray(catalog?.services) ? catalog.services : [])
    .map(s => [s.service_id,s]));
  const engines = Array.isArray(inventory?.engines) ? inventory.engines : [];
  const groups = [];
  const rows = [];
  const group = (title, data) => groups.push({title, rows:data});
  const age = (now - Date.parse(diagnostics?.generated_at))/1000;
  const fresh = !!diagnostics && diagnostics.stale === false && Number.isFinite(age) && age >= -5 && age <= (diagnostics.cache_ttl_seconds || 60);
  const count = n => Number.isSafeInteger(n) && n >= 0 ? String(n) : 'unknown';
  const providerStatus = (items) => {
    if (items.some(s => typeof s?.available !== 'boolean')) return 'unknown';
    const n = items.filter(s => s.available).length;
    return n === items.length ? 'available' : n === 0 ? 'unavailable' : 'degraded';
  };
  function serviceRow(suffix, name, description, note='') {
    const items = ENGINES.map(([prefix]) => services.get(`${prefix}.${suffix}`));
    // Only browser-local I Ching depends on client crypto. Rune Classic is server-side.
    if (suffix === 'classic' && items[0]?.available && !browserCrypto) {
      items[0] = {...items[0], available:false};
    }
    return {name, description, status:providerStatus(items), detail:ENGINES.map(([,label],i) => `${label}: ${items[i]?.available === true ? 'enabled' : items[i]?.available === false ? 'unavailable' : 'unknown'}`).join(' · ') + (note ? ` · ${note}` : '')};
  }
  rows.push(serviceRow('classic','Classic','Browser / server cryptographic randomness',browserCrypto ? 'Browser crypto API present' : 'Browser crypto API unavailable'));
  rows.push(serviceRow('qrng_private','QCI Quantum Noise','Private quantum randomness','No live entropy probe performed'));
  const nist = diagnostics?.services?.['oracle.public_qrng'];
  const nistTimestamp = nist?.checked_at || diagnostics?.generated_at;
  const nistAge = (now - Date.parse(nistTimestamp))/1000;
  const nistFresh = fresh && Number.isFinite(nistAge) && nistAge >= -5 && nistAge <= (diagnostics.cache_ttl_seconds || 60);
  const nistRow = serviceRow('qrng_public','NIST Public Beacon','Public, timestamped randomness',nistFresh && nist?.status ? `Cached provider check: ${readableStatus(nist.status)}${Number.isFinite(nist.latency_ms) ? ` (${nist.latency_ms} ms)` : ''}` : 'Provider check stale or unavailable');
  if (nistFresh && nistRow.status === 'available' && ['unavailable','degraded'].includes(nist?.status)) nistRow.status='degraded';
  rows.push(nistRow);
  rows.push(serviceRow('quantum_future','IBM Quantum Future','New hardware execution','Public admission only; no hardware job submitted'));
  const ai=services.get('iching.ai_enhancement');
  rows.push({name:'AI enhancement',description:'DeepInfra',status:providerStatus([ai]),detail:ai?.available === true ? 'Enabled; no live inference test' : ai?.available === false ? 'Not available through the public catalog' : 'Catalog unavailable'});
  group('ORACLE & AI SERVICES',rows);
  group('IBM QUANTUM PAST INVENTORY',ENGINES.map(([prefix,label]) => {
    const id=`${prefix}.quantum_past`;
    const svc=services.get(id);
    const engine=engines.find(e => e.service_id === id);
    const counts=engine?.counts || svc?.inventory;
    if (!counts) return {name:label,description:'Historical hardware measurements',status:'unknown',detail:'Inventory count unavailable'};
    const stock=counts.available;
    const enabled=svc?.available;
    // Never claim availability from held or unreleased stock, or contradictory snapshots.
    const status=enabled === false || stock === 0 ? 'unavailable' : enabled === true && Number.isSafeInteger(stock) && stock > 0 && (!engine || engine.service_enabled === true) ? 'available' : 'unknown';
    return {name:label,description:'Historical hardware measurements',status,detail:`${count(stock)} available · ${count(counts.pending_release)} awaiting release · ${count(counts.delivered)} delivered`};
  }));
  const batchCount=engines.reduce((n,e)=>n+(Number.isSafeInteger(e.batch_count)&&e.batch_count>=0?e.batch_count:0),0);
  const verified=engines.reduce((n,e)=>n+(Number.isSafeInteger(e.check_counts?.bitcoin_verified)?e.check_counts.bitcoin_verified:0),0);
  const released=engines.reduce((n,e)=>n+(Number.isSafeInteger(e.check_counts?.released)?e.check_counts.released:0),0);
  group('QUANTUM TRANSPARENCY', [{name:'Signed inventory & Bitcoin',description:'Recorded GQTP verification',status:!inventory || !batchCount ? 'unknown' : verified===batchCount && released===batchCount && inventory.inventory_enforced===true ? 'healthy' : 'degraded',detail:!inventory?'Public inventory API unavailable':`Checkpoint ${count(inventory.latest_checkpoint)} · ${verified}/${batchCount} batches Bitcoin verified · ${released}/${batchCount} released · Release enforcement ${inventory.inventory_enforced===true?'on':'not confirmed'}`}]);
  const backends=Array.isArray(diagnostics?.ibm_backends)?diagnostics.ibm_backends:[];
  group('IBM QUANTUM HARDWARE',backends.length ? backends.map(b=>({name:b.name || 'IBM backend',description:Number.isInteger(b.qubits)?`${b.qubits} qubits`:'Quantum processor',status:!fresh?'unknown':b.status || (b.operational===true?'healthy':b.operational===false?'unavailable':'unknown'),detail:!fresh?'Cached hardware status stale':Number.isInteger(b.pending_jobs ?? b.queue) && (b.pending_jobs ?? b.queue)>=0?`${b.pending_jobs ?? b.queue} queued jobs`:'Queue unavailable'})) : [{name:'Live backend monitoring',description:'IBM processor and queue diagnostics',status:'unknown',detail:'No current backend status reported; historical stock is independent'}]);
  return {groups, fresh, partial:!catalog || !inventory || !diagnostics};
}
function render(data) {
  const view=buildHealthView(data.catalog,data.inventory,data.diagnostics,!!globalThis.crypto?.getRandomValues);
  details.replaceChildren();
  for (const group of view.groups) {
    details.append(el('h3','health-section-title',group.title));
    for (const r of group.rows) details.append(statusRow(r.name,r.description,r.status,r.detail));
  }
  const note= view.partial ? 'Some sources unavailable' : 'Public availability updated';
  const diag= view.fresh ? `Provider snapshot ${formatDate(data.diagnostics.generated_at)}` : 'Provider diagnostics stale or unavailable';
  summary.textContent=`${note} · ${diag} · Checked ${formatDate(new Date().toISOString())}`;
  summary.classList.toggle('health-stale',view.partial || !view.fresh);
}
async function readPublicJson(url,signal) {
  const response=await fetch(url,{method:'GET',cache:'no-store',signal});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}
async function getStatus() {
  if (requestInFlight) return requestInFlight;
  requestInFlight=(async()=>{
    summary.textContent='Checking public service availability…';
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),10000);
    try {
      const keys=Object.keys(ENDPOINTS);
      const results=await Promise.allSettled(keys.map(k=>readPublicJson(ENDPOINTS[k],controller.signal)));
      const data=Object.fromEntries(keys.map((k,i)=>[k,results[i].status==='fulfilled'?results[i].value:null]));
      render(data);
      return data;
    } catch(error) {
      details.replaceChildren(el('p','health-empty','Public health data could not be displayed.'));
      summary.textContent='Health data temporarily unavailable';
      summary.classList.add('health-stale');
      return null;
    } finally {clearTimeout(timer);}
  })();
  try {return await requestInFlight;} finally {requestInFlight=null;}
}
function createModal() {
  dialog = document.createElement('dialog');
  dialog.className = 'system-health-dialog';
  dialog.setAttribute('aria-labelledby', 'health-modal-title');

  const header = el('div', 'health-modal-header');

  const heading = el('div');
  heading.append(
    el('p', 'health-eyebrow', 'GNOSIS.BOT / INFRASTRUCTURE'),
    el('h2', '', 'System Health')
  );
  heading.querySelector('h2').id = 'health-modal-title';

  const closeButton = el('button', 'health-close', '×');
  closeButton.type = 'button';
  closeButton.setAttribute('aria-label', 'Close system health');
  closeButton.addEventListener('click', () => dialog.close());

  header.append(heading, closeButton);

  summary = el('p', 'health-summary', 'Checking services…');
  summary.setAttribute('role', 'status');

  details = el('div', 'health-details');

  const footer = el('div', 'health-modal-footer');
  const note = el('span', '', 'Availability is not a live provider test. No paid checks.');

  const refresh = el('button', 'health-refresh', 'Check status');
  refresh.type = 'button';
  refresh.addEventListener('click', () => void getStatus());

  footer.append(note, refresh);

  dialog.append(header, summary, details, footer);

  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });



  document.body.append(dialog);
}

function init() {
  const triggers=document.querySelectorAll('[data-system-health]');
  if (!triggers.length) return;
  createModal();
  triggers.forEach(button=>button.addEventListener('click',()=>{
    if (!dialog.open) dialog.showModal();
    void getStatus();
  }));
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',init,{once:true});
else init();
