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
  closeCommunicationReply();
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
// GNOSIS COMMUNICATIONS V0.4.1 — recipient actions and opt-in replies.
/** Gnosis Communications V0.4.1: authenticated notices and admin-directed replies.
 * Safe DOM/textContent only. Server owns all recipient and reply authorization.
 */
let communicationDialog = null;
let communicationReturnFocus = null;
let communicationReplyNotice = null;
let communicationRequestId = null;
let communicationSending = false;
function closeCommunicationReply(){
  if(communicationDialog?.open) communicationDialog.close();
  communicationReplyNotice = null;
  communicationRequestId = null;
  const body=communicationDialog?.querySelector('textarea');
  if(body)body.value='';
}
function communicationIcon(kind){
  const button=document.createElement('button');button.type='button';
  button.className='gnosis-communication-icon';
  const label=kind==='copy'?'Copy message':'Delete message from my inbox';
  button.setAttribute('aria-label',label);button.title=label;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  const paths=kind==='copy'
    ? ['M8 4H19V17','M5 7H16V20H5Z']
    : ['M4 7H20','M9 7V4H15V7','M6 7L7 21H17L18 7','M10 11V17','M14 11V17'];
  for(const d of paths){const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',d);svg.append(p);}
  button.append(svg);return button;
}
function ensureCommunicationDialog(){
  if(communicationDialog)return communicationDialog;
  const dialog=document.createElement('dialog');dialog.id='gnosis-communication-reply-modal';
  dialog.className='gnosis-communication-dialog';dialog.setAttribute('aria-labelledby','gnosis-communication-reply-title');
  const heading=document.createElement('div');heading.className='gnosis-communication-dialog-heading';
  const h=document.createElement('h2');h.id='gnosis-communication-reply-title';h.textContent='Reply to message';
  const close=document.createElement('button');close.type='button';close.textContent='Close ×';
  close.setAttribute('aria-label','Close reply composer');close.addEventListener('click',()=>dialog.close());
  heading.append(h,close);
  const context=document.createElement('p');context.id='gnosis-communication-reply-context';
  const note=document.createElement('p');note.textContent='Your reply is delivered privately to the original administrator’s Gnosis account inbox. It is not an email or public post.';
  const form=document.createElement('form');form.id='gnosis-communication-reply-form';
  const label=document.createElement('label');label.htmlFor='gnosis-communication-reply-text';label.textContent='Message';
  const textarea=document.createElement('textarea');textarea.id='gnosis-communication-reply-text';
  textarea.maxLength=2500;textarea.required=true;textarea.rows=6;
  const send=document.createElement('button');send.type='submit';send.className='gnosis-communication-send';send.textContent='Send reply';
  const status=document.createElement('p');status.className='gnosis-communication-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  form.append(label,textarea,send,status);dialog.append(heading,context,note,form);
  // Native dialog owns Escape. Do not let the workspace flyout handler close the parent underneath it.
  dialog.addEventListener('keydown',event=>event.stopPropagation());
  dialog.addEventListener('pointerdown',event=>event.stopPropagation());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  dialog.addEventListener('close',()=>{
    if(communicationReturnFocus?.isConnected&&isAuthed())communicationReturnFocus.focus();
    communicationReturnFocus=null;communicationReplyNotice=null;communicationRequestId=null;
    textarea.value='';status.textContent='';send.disabled=false;communicationSending=false;
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(communicationSending||!communicationReplyNotice||!isAuthed())return;
    const body=textarea.value.trim();
    if(!body||body.length>2500){status.textContent='Enter a reply of 1–2500 characters.';status.dataset.error='true';return;}
    const noticeId=communicationReplyNotice;
    communicationRequestId ||= crypto.randomUUID().replaceAll('-','');
    communicationSending=true;send.disabled=true;status.dataset.error='false';status.textContent='Sending reply…';
    try{
      const result=await requestJSON(`/api/v1/accounts/notices/${noticeId}/reply`,{
        method:'POST',body:JSON.stringify({body,client_request_id:communicationRequestId})
      });
      if(!isAuthed()||result?.sent!==true)throw new Error('Reply could not be confirmed');
      status.textContent='Reply delivered to the administrator’s account inbox.';
      textarea.value='';communicationReplyNotice=null;communicationRequestId=null;
      send.disabled=true;
    }catch(error){status.textContent='Unable to send reply. Check your connection or retry.';status.dataset.error='true';send.disabled=false;}
    finally{communicationSending=false;}
  });
  document.body.append(dialog);communicationDialog=dialog;return dialog;
}
function openCommunicationReply(item,button){
  if(!isAuthed()||item?.reply_enabled!==true||typeof item.notice_id!=='string'||!/^[0-9a-f]{32}$/.test(item.notice_id))return;
  const dialog=ensureCommunicationDialog();
  communicationReturnFocus=button;communicationReplyNotice=item.notice_id;communicationRequestId=null;
  dialog.querySelector('#gnosis-communication-reply-context').textContent='Regarding: '+item.title.slice(0,160);
  dialog.querySelector('.gnosis-communication-status').textContent='';
  dialog.querySelector('.gnosis-communication-send').disabled=false;
  dialog.showModal();dialog.querySelector('textarea').focus();
}
async function hideCommunicationMessage(item,button){
  if(!isAuthed()||typeof item?.message_id!=='string'||!/^[0-9a-f]{32}$/.test(item.message_id)||!['notice','reply'].includes(item.message_type))return;
  if(!window.confirm('Delete this message from your inbox? It will remain in the sender’s records.'))return;
  button.disabled=true;
  try{
    await requestJSON(`/api/v1/accounts/notices/${item.message_id}/hide`,{
      method:'POST',body:JSON.stringify({message_type:item.message_type})
    });
    if(isAuthed())await getNotices(generation);
  }catch(error){button.disabled=false;button.title='Unable to delete message. Retry.';}
}
function appendNotices(data) {
  noticeItems.replaceChildren();
  if(data?.schema!=='gnosis.account-notices.v1'||!Array.isArray(data.items)) {
    noticeItems.append(par('gnosis-message-placeholder','Account messages are currently unavailable.'));return;
  }
  if(!data.items.length){noticeItems.append(par('gnosis-message-placeholder','No new account messages.'));return;}
  for(const item of data.items.slice(0,12)){
    if(!item||typeof item.title!=='string'||!item.title.trim()||typeof item.body!=='string')continue;
    const card=document.createElement('article');card.className='gnosis-message-item';
    const head=document.createElement('div');head.className='gnosis-communication-item-head';
    const h=document.createElement('h4');h.textContent=item.title.slice(0,160);
    head.append(h);
    const actions=document.createElement('div');actions.className='gnosis-communication-item-actions';
    const copy=communicationIcon('copy');
    copy.addEventListener('click',async()=>{
      const textToCopy=item.title+'\n\n'+item.body;
      try{
        await navigator.clipboard.writeText(textToCopy);
        copy.title='Copied to clipboard';copy.setAttribute('aria-label','Message copied to clipboard');
      }catch{copy.title='Clipboard unavailable';copy.setAttribute('aria-label','Clipboard unavailable');}
    });
    actions.append(copy);
    if(/^[0-9a-f]{32}$/.test(item.message_id||'')&&['notice','reply'].includes(item.message_type)){
      const del=communicationIcon('delete');
      del.addEventListener('click',()=>void hideCommunicationMessage(item,del));actions.append(del);
    }
    head.append(actions);card.append(head,par('',item.body.slice(0,4000)));
    if(typeof item.from_account==='string' && item.message_type==='reply'){
      card.append(par('gnosis-communication-from','From account '+item.from_account.slice(0,24)));
    }
    const footer=document.createElement('div');footer.className='gnosis-communication-footer';
    if(typeof item.published_at==='string'&&!Number.isNaN(Date.parse(item.published_at))){
      const t=document.createElement('small');t.textContent=new Date(item.published_at).toLocaleDateString();footer.append(t);
    }
    const href=safeSameOrigin(item.action?.href);
    if(href&&typeof item.action?.label==='string'&&item.action.label.trim()){
      const a=document.createElement('a');a.href=href;a.textContent=item.action.label.slice(0,100);footer.append(a);
    }
    if(item.message_type==='notice' && item.reply_enabled===true){
      const reply=document.createElement('button');reply.type='button';reply.className='gnosis-communication-reply-link';reply.textContent='Reply';
      reply.addEventListener('click',()=>openCommunicationReply(item,reply));footer.append(reply);
    }
    card.append(footer);noticeItems.append(card);
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
