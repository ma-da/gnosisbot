/** GNOSIS / Account commerce + notices UI v1. No payment logic, no wallet handling.
 * Server owns prices, legal terms, authentication, audience routing, credit settlement.
 * Fails closed: nothing can be purchased without a validated server quote. */
const $ = (id) => document.getElementById(id);
const root = $('gnosis-credit-store');
const noticeRoot = $('gnosis-account-messages');
if (!root || !noticeRoot) throw new Error('Account commerce markup missing');

const IDS = Object.freeze(['stripe','solana','rstory']);
const methods = [...root.querySelectorAll('input[name="gnosis-credit-method"]')];
const offersNode = $('gnosis-credit-offers');
const orderTerms = $('gnosis-credit-agree');
const submit = $('gnosis-credit-submit');
const message = $('gnosis-credit-status');
const noticeItems = $('gnosis-message-items');
let generation = 0;
let quoteSerial = 0;
let store = null;
let offerId = null;
let quote = null;
let submitting = false;
let lastCheckoutKey = null;

const txt = (id, value) => {const el = $(id); if (el) el.textContent = String(value);};
const status = (s, error = false) => {message.textContent=s; message.dataset.error=String(error);};
const enabledMethod = () => methods.find(m => m.checked && !m.disabled)?.value || null;
const fmtCredits = n => Number(n).toLocaleString('en-US') + ' credits';
const validCount = n => Number.isSafeInteger(n) && n > 0 && n <= 1000000;
const methodOK = m => IDS.includes(m);
const safeSameOrigin = value => {
  if (typeof value !== 'string') return null;
  try {const u=new URL(value,location.origin);return u.origin===location.origin && ['https:','http:'].includes(u.protocol) && !u.username && !u.password ? u.href : null;}
  catch {return null;}
};
const safeCheckoutUrl = (value, method) => {
  if (typeof value !== 'string') return null;
  try {
    const u=new URL(value,location.origin);
    if (u.username || u.password || u.protocol!=='https:') return null;
    if (u.origin===location.origin) return u.href;
    if (method==='stripe' && u.hostname==='checkout.stripe.com') return u.href;
  } catch {}
  return null;
};
const isAuthed = () => document.body.dataset.gnosisSession==='authenticated';
function clearQuote() {
  quoteSerial++; quote=null;lastCheckoutKey=null;orderTerms.checked=false;
  txt('gnosis-credit-amount', '—');txt('gnosis-credit-quantity', '—');
  txt('gnosis-credit-fees', '—');txt('gnosis-credit-network', '—');
  txt('gnosis-credit-refund', 'Refund conditions will be shown with a live quote.');
  submit.disabled=true;
}
function reset() {
  generation++;store=null;offerId=null;submitting=false;clearQuote();
  for (const m of methods) {m.disabled=false;m.checked=m.value==='stripe';}
  offersNode.replaceChildren();
  offersNode.append(par('gnosis-credit-empty','Credit packages and prices will appear when checkout is available.'));
  txt('gnosis-credit-state', 'CHECKOUT NOT YET ENABLED');
  status('No payment can be made on this page yet.');
  noticeItems.replaceChildren();
  noticeItems.append(par('gnosis-message-placeholder','Account messages will appear here when available.'));
}
function par(klass, content) {const p=document.createElement('p');p.className=klass;p.textContent=content;return p;}
function selectedOffer(){return store?.offers.find(o=>o.id===offerId) || null;}
function drawOffers() {
  offersNode.replaceChildren();
  if (!store || !store.offers.length){
    offersNode.append(par('gnosis-credit-empty','No credit packages are currently available.'));
    return;
  }
  for (const o of store.offers){
    const b=document.createElement('button');b.type='button';b.className='gnosis-credit-offer';
    b.setAttribute('aria-pressed',String(offerId===o.id));b.textContent=fmtCredits(o.credits);
    const s=document.createElement('span');s.textContent='Get a live price';b.append(s);
    b.addEventListener('click',()=>{if(submitting)return;offerId=o.id;clearQuote();drawOffers();void getQuote();});
    offersNode.append(b);
  }
}
async function requestJSON(url, options = {}) {
  const res=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{})},...options});
  if (!res.ok) {const err=new Error(`Unavailable (${res.status})`);err.status=res.status;throw err;}
  return await res.json();
}
function validStore(data) {
  if (!data || data.schema!=='gnosis.credit-storefront.v1' || data.enabled!==true ||
      typeof data.terms_version!=='string' || !/^[A-Za-z0-9_.:-]{1,80}$/.test(data.terms_version) ||
      !Array.isArray(data.offers) || !Array.isArray(data.methods)) return null;
  const offers=data.offers.filter(o=>o && typeof o.id==='string' && /^[a-zA-Z0-9_.-]{1,80}$/.test(o.id) && validCount(o.credits)).slice(0,12);
  const ids=new Set();const distinct=offers.filter(o=>!ids.has(o.id)&&ids.add(o.id));
  const enabled=new Set(data.methods.filter(m=>m&&methodOK(m.id)&&m.enabled===true).map(m=>m.id));
  if (!enabled.size || !distinct.length) return null;
  return {offers:distinct,enabled,termsVersion:data.terms_version};
}
async function getStore(epoch) {
  try{
    const data=await requestJSON('/api/v1/accounts/credits/storefront');
    if(epoch!==generation||!isAuthed())return;
    store=validStore(data);
    if (!store){status('Credit checkout is not available yet.');return;}
    for(const m of methods)m.disabled=!store.enabled.has(m.value);
    const chosen=methods.find(m=>m.checked&&!m.disabled) || methods.find(m=>!m.disabled);
    for(const m of methods)m.checked=m===chosen;
    offerId=store.offers[0].id;
    txt('gnosis-credit-state','LIVE PRICING AVAILABLE');
    drawOffers();await getQuote();
  }catch(error){if(epoch!==generation||!isAuthed())return;
    txt('gnosis-credit-state','CHECKOUT NOT YET ENABLED');
    status('Purchases are not available yet. No payment can be made.',false);
  }
}
async function getQuote() {
  const method=enabledMethod(), offer=selectedOffer(), epoch=generation;
  clearQuote();const serial=quoteSerial;
  if(!isAuthed()||!store||!offer||!method){return;}
  status('Checking current price…');
  try{
    const data=await requestJSON('/api/v1/accounts/credits/quote',{
      method:'POST',body:JSON.stringify({offer_id:offer.id,method})});
    if(epoch!==generation||serial!==quoteSerial||!isAuthed())return;
    if(data?.schema!=='gnosis.credit-quote.v1' || data.method!==method ||
       data.offer_id!==offer.id || data.credits!==offer.credits ||
       typeof data.quote_id!=='string' || !/^[a-zA-Z0-9_.:-]{8,128}$/.test(data.quote_id) ||
       typeof data.total_display!=='string' || !data.total_display.trim() || data.total_display.length>512 ||
       typeof data.refund_summary!=='string' || !data.refund_summary.trim() || data.refund_summary.length>700 ||
       typeof data.expires_at!=='string' || !(Date.parse(data.expires_at)>Date.now()))throw new Error('Incomplete quote');
    quote=data;
    txt('gnosis-credit-amount', data.total_display);
    txt('gnosis-credit-quantity', fmtCredits(offer.credits));
    txt('gnosis-credit-fees', typeof data.fees_display==='string' ? data.fees_display.slice(0,110) : 'Included in total');
    txt('gnosis-credit-network', typeof data.payment_detail==='string' ? data.payment_detail.slice(0,130) : '—');
    txt('gnosis-credit-refund', data.refund_summary);
    status('Quote ready. Review the amount and terms before continuing.');
    submit.disabled=!orderTerms.checked;
  }catch(error){if(epoch!==generation||serial!==quoteSerial||!isAuthed())return;
    clearQuote();status('A current, complete checkout quote is unavailable. No payment has been requested.');}
}
for(const m of methods)m.addEventListener('change',()=>{if(!m.checked||submitting)return;void getQuote();});
orderTerms.addEventListener('change',()=>{submit.disabled=submitting||!quote||!orderTerms.checked;});
submit.addEventListener('click',async()=>{
  if(submitting||!isAuthed()||!quote||!store||!orderTerms.checked)return;
  if(!(Date.parse(quote.expires_at)>Date.now())){clearQuote();status('Quote expired. Request a new price.',true);return;}
  submitting=true;submit.disabled=true;
  status('Preparing your checkout. No credits are issued until payment verification.');
  const idempotencyKey=lastCheckoutKey||(lastCheckoutKey=crypto.randomUUID());
  try{
    const response=await requestJSON('/api/v1/accounts/credits/checkout',{
      method:'POST',body:JSON.stringify({quote_id:quote.quote_id,idempotency_key:idempotencyKey,
        legal_acceptance:{accepted:true,terms_version:store.termsVersion}})});
    const target=safeCheckoutUrl(response?.checkout_url,quote.method);
    if(response?.schema!=='gnosis.credit-checkout.v1'||response?.status!=='ready'||!target){
      throw new Error('Checkout destination was not verified');
    }
    window.location.assign(target);
  }catch(error){status('Unable to start checkout. No credits have been issued. Try again or contact support.',true);}
  finally{submitting=false;submit.disabled=!quote||!orderTerms.checked;}
});
function appendNotices(data) {
  noticeItems.replaceChildren();
  if(data?.schema!=='gnosis.account-notices.v1'||!Array.isArray(data.items)) {
    noticeItems.append(par('gnosis-message-placeholder','Account messages are currently unavailable.'));return;
  }
  if(!data.items.length){noticeItems.append(par('gnosis-message-placeholder','No new account messages.'));return;}
  for(const x of data.items.slice(0,12)){
    if(!x||typeof x.title!=='string'||!x.title.trim()||typeof x.body!=='string')continue;
    const card=document.createElement('article');card.className='gnosis-message-item';
    const h=document.createElement('h4');h.textContent=x.title.slice(0,160);
    const p=par('',x.body.slice(0,4000));card.append(h,p);
    if(typeof x.published_at==='string' && !Number.isNaN(Date.parse(x.published_at))){
      const t=document.createElement('small');t.textContent=new Date(x.published_at).toLocaleDateString();card.append(t);
    }
    const href=safeSameOrigin(x.action?.href);
    if(href&&typeof x.action?.label==='string'&&x.action.label.trim()){
      const a=document.createElement('a');a.href=href;a.textContent=x.action.label.slice(0,100);card.append(a);
    }
    noticeItems.append(card);
  }
  if(!noticeItems.children.length)noticeItems.append(par('gnosis-message-placeholder','No new account messages.'));
}
async function getNotices(epoch){
  try{const data=await requestJSON('/api/v1/accounts/notices');
    if(epoch===generation&&isAuthed())appendNotices(data);
  }catch{if(epoch===generation&&isAuthed())appendNotices(null);}
}
function syncAuth() {
  const authenticated=isAuthed();root.hidden=!authenticated;noticeRoot.hidden=!authenticated;
  if(!authenticated){reset();return;}
  reset();
  const epoch=generation;
  void getStore(epoch);void getNotices(epoch);
}
let prior=document.body.dataset.gnosisSession;
const observer=new MutationObserver(()=>{
  const next=document.body.dataset.gnosisSession;
  if(prior===next)return;prior=next;syncAuth();
});
observer.observe(document.body,{attributes:true,attributeFilter:['data-gnosis-session']});
window.addEventListener('gnosis:account-session-changed',()=>{
  // Immediately remove private content on login/logout/account switch.
  // The hub owns authorization and will reveal sections after verification.
  root.hidden=true; noticeRoot.hidden=true; reset();
  prior='loading'; // Reauthorize on the hub's next completed session state update.
});
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden&&isAuthed()&&store){clearQuote();void getQuote();}
});
syncAuth();
