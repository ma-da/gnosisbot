import { faceButton } from './reading-resonance.js?v=1';
/** Gnosis account hub v1. Service-neutral activity; private data only from authenticated API.
 * Remote IBM processing is NEVER initiated or settled by this browser script.
 */
const $ = id => document.getElementById(id);
const activity = $('gnosis-hub-activity');
const banner = $('gnosis-hub-status');
let page = 0;
const requestedMode = new URLSearchParams(location.search).get('mode');
const initialMode = ['coins','pouch','sticks'].includes(requestedMode) ? requestedMode : 'coins';
let readingMode = initialMode;
const limit = 25;
let refreshTimer = null;
const focusedId = (new URLSearchParams(location.search).get('reading') || '').toLowerCase();
const validId = /^[0-9a-f]{32}$/;
let focusPending=validId.test(focusedId);
const focusCertificate=new URLSearchParams(location.search).get('certificate')==='1';
let loadGeneration = 0;
let emailConfirmationActive = false;
let emailChangeOpen = false; // GNOSIS ACCOUNT IDENTITY V0.5

// The verified hub endpoint is authoritative for the signed-in dashboard.
// Keep the key manager's login/create workflow untouched.
function setAccountView(state) {
  document.body.dataset.gnosisSession = state;
  const auth = $('account-auth-view');
  const hub = $('gnosis-account-hub');
  const loading = $('account-loading-state');
  if (auth) auth.hidden = state !== 'guest';
  if (hub) hub.hidden = state !== 'authenticated';
  if (loading) loading.hidden = state !== 'loading';
  if (state !== 'authenticated') {
    const panel = $('gnosis-hub-panel');
    if (panel) panel.hidden = true;
  }
  if (state === 'guest') {
    emailChangeOpen = false;
    // Scrub previously rendered private activity from the signed-out DOM.
    activity.replaceChildren();
    for (const id of ['gnosis-hub-available', 'gnosis-hub-reserved',
                      'gnosis-hub-total', 'gnosis-hub-pending-count']) {
      text(id, '—');
    }
    text('gnosis-hub-email-status', 'Not signed in');
  }
}

function el(tag,klass,value){
  const node=document.createElement(tag);
  if(klass)node.className=klass;
  if(value!==undefined)node.textContent=String(value);
  return node;
}
function text(id,val){const node=$(id);if(node)node.textContent=String(val);}
function urlPath(s){return typeof s==='string' && /^\/[A-Za-z0-9_/?=&%.-]+$/.test(s) ? s : null;}
function pretty(date){const d=new Date(date);return Number.isNaN(d.getTime())?'':d.toLocaleString();}
function labelFor(item){
  if(item.service_id==='iching.quantum_future')return 'IBM Quantum · 128-shot medoid';
  if(item.service_id==='iching.qci' || item.provider==='qci')return 'Quantum randomness · QCI';
  return item.service_id || item.application_id || 'Gnosis service';
}
function displayStatus(item){
  if(item.status==='completed')return 'Completed';
  if(item.status==='failed' || item.status==='cancelled')return 'Not completed';
  return ({queued:'Queued for IBM',submitting:'Submitting to IBM',submitted:'Submitted to IBM',
           running:'Running on IBM',result_ready:'Verifying measurements',
           needs_reconciliation:'Needs operator review'}[item.hardware_status] || 'Pending');
}
function renderApplications(apps){
  const nav=$('gnosis-hub-apps');
  if(!nav)return;
  nav.replaceChildren();
  for(const app of Array.isArray(apps)?apps:[]){
    const href=urlPath(app.href);
    if(!href)continue;
    const link=el('a','gnosis-hub-app-link',app.label||app.id||'Application');
    link.href=href;nav.append(link);
  }
  for(const [href,label] of [['#gnosis-hub-activity-title','Your activity'],
      ['#gnosis-hub-email-title','Notifications']]){
    const a=el('a',null,label);a.href=href;nav.append(a);
  }
}
function render(items,total,pending){
  activity.replaceChildren();
  if (items.some(item => item.resonance)) activity.append(el('p','gnosis-resonance-hint','Tap a face to mark a reading that resonated. Tap again to unmark.'));
  $('gnosis-hub-prev').disabled=page===0;
  $('gnosis-hub-next').disabled=(page+1)*limit>=total;
  text('gnosis-hub-page',`${total?1+page*limit:0}–${Math.min(total,(page+1)*limit)} of ${total}`);
  text('gnosis-hub-pending-count',String(pending));
  if(!items.length)activity.append(el('p','gnosis-empty',`No saved ${readingMode} readings on this page. Classic browser-only casts are not stored.`));
  for(const item of items){
    const card=el('article','gnosis-activity-item');
    card.dataset.service=item.service_id||'';
    card.dataset.status=item.status;
    if(focusedId===item.consultation_id){card.classList.add('gnosis-highlight');card.id='gnosis-focused-reading';}
    const head=el('div','gnosis-activity-header');
    head.append(el('h3','gnosis-activity-title',labelFor(item)));
    head.append(el('span','gnosis-activity-state',displayStatus(item)));
    card.append(head);
    card.append(el('p','gnosis-activity-meta',`${pretty(item.created_at)} · ${item.credits_cost||0} credits`));
    if(item.question)card.append(el('p','gnosis-activity-question',item.question));
    if(item.backend)card.append(el('p','gnosis-activity-meta',`${item.backend} · ${item.shots||'—'} shots`));
    if(item.status==='pending'){
      card.append(el('p','gnosis-activity-note','Your reserved credits are not permanently charged until the result is completed.'));
    }
    if(item.email_status==='awaiting_contact'){
      card.append(el('p','gnosis-activity-note','Reading stored. Verify an email address to enable a completion notice.'));
    }
    if(item.email_status==='needs_review'){
      card.append(el('p','gnosis-activity-note','Reading is saved; email delivery requires review.'));
    }
    if(item.certificate_status!=='ready' && item.certificate_event_state==='pending'){
      card.append(el('p','gnosis-activity-note','Preparing certificate. Refresh activity to view it when ready.'));
    }
    if(item.certificate_event_state==='blocked'){
      card.append(el('p','gnosis-activity-note','Reading saved. Certificate processing requires operator review.'));
    }
    const open=urlPath(item.open_url);
    if(open){
      const a=el('a','gnosis-activity-open',item.service_id==='iching.quantum_future'
        ? 'Play Your New Reading' : 'Open saved reading');
      a.href=open;card.append(a);
    }
    if (item.certificate_status === 'ready' && validId.test(item.consultation_id) && validId.test(item.certificate_id)) {
      const base = `/api/v1/accounts/readings/${item.consultation_id}/certificate`;
      // Pin the exact revision returned by the authenticated hub, not a cached unversioned URL.
      const image = `${base}.png?certificate_id=${item.certificate_id}`;
      const links = el('div','gnosis-certificate-actions');
      const view = el('a','gnosis-certificate-action','View certificate'); if(focusCertificate&&focusedId===item.consultation_id)view.id='gnosis-focused-certificate'; view.href=image; view.target='_blank'; view.rel='noopener noreferrer';
      const dl = el('a','gnosis-certificate-action','Download PNG'); dl.href=image+'&download=true';
      const share = el('button','gnosis-certificate-action','Share certificate'); share.type='button';
      const revoke = el('button','gnosis-certificate-action','Revoke link'); revoke.type='button';
      const status = el('p','gnosis-certificate-status'); status.setAttribute('role','status'); status.hidden=true;
      const setStatus = (message) => {status.textContent=message;status.hidden=!message;};
      const setBusy = busy => {share.disabled=busy;revoke.disabled=busy;};
      const shareAction = async method => {
        setBusy(true);setStatus('');
        try {
          const res=await fetch(base+'/share'+(method==='POST'?'?certificate_id='+item.certificate_id:''),{method,credentials:'same-origin',cache:'no-store'});
          if(!res.ok){setStatus(`Certificate request failed (HTTP ${res.status}). ${res.status===401?'Sign in again.':res.status===404?'Refresh the account page or ask the operator to check certificate routes.':res.status===403?'Check the site origin or sign in again.':res.status===409?'A newer certificate exists. Refresh the account page.':'Please contact the operator.'}`);return;}
          const data=await res.json();
          if(method==='POST'){
            if(typeof data.share_path!=='string'||!/^\/api\/v1\/c\/[A-Za-z0-9_-]{43}$/.test(data.share_path))throw Error('invalid share response');
            if(data.certificate_id!==item.certificate_id){setStatus('A newer certificate revision exists. Refresh your account before sharing.');return;}
            const url=new URL(data.share_path,location.origin);
            if(url.origin!==location.origin)throw Error('invalid origin');
            window.prompt('Copy your public certificate link:',url.href);
            setStatus('Public link created. Anyone with the link can view this certificate.');
          }else{
            if(data.revoked!==true)throw Error('invalid revocation response');
            setStatus('Certificate links revoked. Previously downloaded copies cannot be recalled.');
          }
        }catch{setStatus('Certificate request failed. Check your connection and try again.');}finally{setBusy(false);}
      };
      share.addEventListener('click',()=>{if(confirm('Publish this question-free certificate? Anyone with the link can view it. Creating a new link revokes the previous link.'))void shareAction('POST');});
      revoke.addEventListener('click',()=>{if(confirm('Revoke all public certificate links for this reading?'))void shareAction('DELETE');});
      links.append(view,dl,share,revoke); card.append(links,status);
    }
    const resonanceFace = faceButton(item);
    if (resonanceFace) head.append(resonanceFace);
    activity.append(card);
  }
  if(focusedId && validId.test(focusedId)){
    const current=activity.querySelector('.gnosis-highlight');
    current?.scrollIntoView({block:'nearest',behavior:'smooth'});
  }
}
function scheduleRefresh(pending){
  if(refreshTimer){clearTimeout(refreshTimer);refreshTimer=null;}
  if(pending>0 && !document.hidden){refreshTimer=setTimeout(()=>void load(),30000);}
}
async function load(){
  const generation = ++loadGeneration;
  if(refreshTimer){clearTimeout(refreshTimer);refreshTimer=null;}
  banner.textContent='Refreshing account activity…';
  try{
    const res=await fetch(`/api/v1/accounts/hub?limit=${limit}&offset=${page*limit}&mode=${readingMode}${focusPending?'&focus='+focusedId:''}`,
        {credentials:'same-origin',cache:'no-store'});
    if (generation !== loadGeneration) return;
    if(res.status===401){
      setAccountView('guest');
      banner.textContent='Sign in with your Gnosis key to view your private activity.';
      return;
    }
    if(!res.ok)throw new Error(`Account activity unavailable (${res.status})`);
    const data=await res.json();
    if (generation !== loadGeneration) return;
    setAccountView('authenticated');
    // GNOSIS EMAIL VERIFICATION UX V1: the link opens a distinct confirm-only view.
    const emailConfirmationPending = Boolean(verifyToken && emailConfirmationActive);
    $('gnosis-email-verification').hidden = !emailConfirmationPending;
    $('gnosis-hub-email-form').hidden = emailConfirmationPending;
    $('gnosis-hub-panel').hidden=false;
    text('gnosis-hub-available',data.account.credits);
    text('gnosis-hub-reserved',data.account.reserved);
    text('gnosis-hub-total',data.account.total);
    const contact=data.email||{verified:false};
    text('gnosis-hub-email-status',emailConfirmationPending
         ? 'Verification link recognized. Confirm this email address below to finish registration.'
         : contact.verified ? `Verified: ${contact.masked_email}`
         : 'No verified notification email');
    // Verified contacts stay compact. An emailed confirmation link always takes
    // priority and shows ONLY the confirm action until it is consumed.
    const pendingEmailLink = Boolean(verifyToken && emailConfirmationActive);
    const changeEmail = $('gnosis-hub-email-change');
    if (changeEmail) {
      changeEmail.hidden = pendingEmailLink || !contact.verified;
      changeEmail.textContent = emailChangeOpen ? 'Cancel change' : 'Change email';
      $('gnosis-hub-email-form').hidden = pendingEmailLink || (contact.verified && !emailChangeOpen);
    }
    renderApplications(data.applications);
    const wasFocused=focusPending;
    page=Math.floor(data.activity.offset/limit);
    render(data.activity.items,data.activity.total,data.activity.pending);
    if(wasFocused){
      const target=$(focusCertificate?'gnosis-focused-certificate':'gnosis-focused-reading') || $('gnosis-focused-reading');
      if(target){focusPending=false;target.scrollIntoView({block:'center'});}
    }
    banner.textContent=`${data.activity.total} ${readingMode} reading${data.activity.total===1?'':'s'} in this archive.`;
    scheduleRefresh(data.activity.pending);
  }catch(error){
    if (generation !== loadGeneration) return;
    if(document.body.dataset.gnosisSession==='loading') setAccountView('guest');
    banner.textContent=error.message||'Unable to refresh account activity';
    const authStatus=$('status');
    if(authStatus && document.body.dataset.gnosisSession==='guest') {
      authStatus.textContent='Account service unavailable. Sign-in may be temporarily affected.';
    }
  }
}
const readingTabs = [...document.querySelectorAll('[data-reading-mode]')];
function showReadingMode(next) {
  if (!['coins','pouch','sticks'].includes(next)) return;
  readingMode = next;
  page = 0;
  for (const tab of readingTabs) {
    const active = tab.dataset.readingMode === next;
    tab.setAttribute('aria-selected',String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active) activity.setAttribute('aria-labelledby',tab.id);
  }
  activity.replaceChildren();
  void load();
}
for (const tab of readingTabs) {
  tab.addEventListener('click',()=>{focusPending=false;showReadingMode(tab.dataset.readingMode);});
  tab.addEventListener('keydown',event=>{
    const index=readingTabs.indexOf(tab);
    const next=event.key==='ArrowRight'?readingTabs[(index+1)%readingTabs.length]:
               event.key==='ArrowLeft'?readingTabs[(index+readingTabs.length-1)%readingTabs.length]:
               event.key==='Home'?readingTabs[0]:event.key==='End'?readingTabs[readingTabs.length-1]:null;
    if (!next) return;
    event.preventDefault();
    next.focus();
    focusPending=false;
    showReadingMode(next.dataset.readingMode);
  });
}
$('gnosis-hub-refresh')?.addEventListener('click',()=>void load());
$('gnosis-hub-prev')?.addEventListener('click',()=>{focusPending=false;page=Math.max(0,page-1);void load();});
$('gnosis-hub-next')?.addEventListener('click',()=>{focusPending=false;page++;void load();});
window.addEventListener('gnosis:account-session-changed',()=>{showReadingMode(focusPending?initialMode:readingMode);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)void load();else scheduleRefresh(0);});
$('gnosis-hub-email-change')?.addEventListener('click', () => {
  emailChangeOpen = !emailChangeOpen;
  const button = $('gnosis-hub-email-change');
  if (button) button.textContent = emailChangeOpen ? 'Cancel change' : 'Change email';
  const form = $('gnosis-hub-email-form');
  if (form) form.hidden = !emailChangeOpen;
  if (emailChangeOpen) $('gnosis-hub-email')?.focus();
});
$('gnosis-hub-email-form')?.addEventListener('submit',async event=>{
  event.preventDefault();
  const input=$('gnosis-hub-email');
  const btn=$('gnosis-hub-email-send');btn.disabled=true;
  text('gnosis-hub-email-message','Sending verification email…');
  try{
    const res=await fetch('/api/v1/accounts/email/start',{
      method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email:input.value.trim()})});
    if(!res.ok)throw new Error(`Verification request unavailable (${res.status})`);
    input.value='';text('gnosis-hub-email-message','Check your inbox. Use the verification link within one hour.');
  }catch(e){text('gnosis-hub-email-message',e.message||'Unable to send verification email');}
  finally{btn.disabled=false;}
});
const verifyToken=new URLSearchParams(location.search).get('verify_email');
emailConfirmationActive = Boolean(verifyToken);
if(verifyToken){
  // GNOSIS EMAIL VERIFICATION UX V1: make the signed-out path explicit as well.
  const authIntro=document.querySelector('#account-auth-view .account-auth-intro');
  if(authIntro){
    authIntro.append(el('p','gnosis-email-verification-login-note',
      'Verification link received. Sign in with the same Gnosis account to finish confirming your email.'));
  }
  history.replaceState(null,'',location.pathname+'?view=profile');
  // This confirmation stays hidden until the account session is verified.
  // The authenticated view displays it after /accounts/hub succeeds.
  $('gnosis-email-confirm').addEventListener('click',async ()=>{
    const btn=$('gnosis-email-confirm');btn.disabled=true;
    try{
      const res=await fetch('/api/v1/accounts/email/confirm',{
        method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({token:verifyToken})});
      if(!res.ok)throw new Error(`Unable to verify (${res.status}). Sign in and retry.`);
      text('gnosis-email-verify-message','Your email is verified for future notifications.');
      emailConfirmationActive = false;
      $('gnosis-email-verification').hidden=true;
      $('gnosis-hub-email-form').hidden=false;
      text('gnosis-hub-email-status','Email verified. Updating account status…');
      void load();
    }catch(error){text('gnosis-email-verify-message',error.message);}
    finally{btn.disabled=false;}
  });
}
showReadingMode(initialMode);
