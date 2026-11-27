// Phase 2 contacts UI; standalone module, fully isolated from dashboard.js internals.
const $ = id => document.getElementById(id);
const fmt = n => n===null||n===undefined?'—':Number(n).toLocaleString();
const composer = $('mail-composer');
async function request(path, options={}) {
  const r=await fetch(path,{credentials:'same-origin',cache:'no-store',...options});
  if(!r.ok){
    let msg=r.status===401?'Sign in first.':r.status===403?'Administrator access required.':`Request failed (${r.status}).`;
    try{const body=await r.json();if(typeof body.detail==='string')msg=body.detail;}catch{}
    throw new Error(msg);
  }
  return r.json();
}

let contactOffset=0, contactBusy=false, currentSendEnabled=false;
const node=(tag,text,cls)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x;};
const mailStatus=s=>{$('mail-feedback').textContent=s;};

let quarantineView=false;
const spamSummary=node('p','Spam protection: loading…');
spamSummary.setAttribute('role','status');
const quarantineToggle=node('button','Review quarantine','secondary');quarantineToggle.type='button';
$('contact-unread-status').insertAdjacentElement('beforebegin',spamSummary);
spamSummary.insertAdjacentElement('afterend',quarantineToggle);
quarantineToggle.addEventListener('click',()=>{if(contactBusy)return;quarantineView=!quarantineView;loadContacts();});

async function loadContacts({more=false}={}){
  if(contactBusy)return;contactBusy=true;
  if(!more){contactOffset=0;$('site-contact-list').replaceChildren();}
  $('contact-unread-status').textContent='Loading contact submissions…';
  try{
    const p=await request('/api/v1/admin/contact-messages?limit=50&offset='+contactOffset+'&quarantine='+quarantineView);
    if(!p.configured){
      $('contact-native-summary').textContent='Native site inbox: not enabled';
      $('contact-unread-count').textContent='— unread';
      $('contact-unread-status').textContent='Contact storage is disabled pending migration and activation; Contact form is unavailable.';
      $('site-contact-more').hidden=true;return;
    }
    $('contact-native-summary').textContent=`Native submissions: ${fmt(p.counts.total)} total · ${fmt(p.counts.unread)} unread`;
    $('contact-unread-count').textContent=`${fmt(p.counts.unread)} unread`;
    if(p.spam)spamSummary.textContent=`Last 24h: ${fmt(p.spam.accepted)} accepted · ${fmt(p.spam.quarantined)} quarantined · ${fmt(p.spam.rejected)} rejected · ${fmt(p.spam.rate_limited)} rate limited`;
    quarantineToggle.textContent=quarantineView?'Return to inbox':`Review quarantine (${fmt(p.counts.quarantine)})`;
    if(Number(p.counts.unread)>0) $('site-contact-disclosure').open=true;
    $('contact-unread-status').textContent=p.messages.length?'Unread items appear in black; use the controls to mark reviewed or archive.':'No messages in this page.';
    for(const message of p.messages){
      const item=node('details',undefined,'contact-message'+(!message.read_at&&!message.archived_at?' contact-message--unread':''));
      const head=node('summary');
      head.append(node('span',message.name),node('time',message.created_at.slice(0,16).replace('T',' ')+' UTC'));
      if(message.quarantine_reason)head.append(node('span',message.quarantine_reason.replaceAll('_',' '),'contact-mini-tag'));
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
      const deleteButton=node('button','Delete','secondary');deleteButton.type='button';
      deleteButton.addEventListener('click',async()=>{
        if(!window.confirm('Permanently remove this website submission from Gnosis? Its stored name, email and message will be erased. Minimal audit history and separately sent emails remain.'))return;
        deleteButton.disabled=true;
        try{await request('/api/v1/admin/contact-messages/'+message.id+'/state',{
          method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete'})
        });await loadContacts();}catch(e){$('contact-unread-status').textContent=e.message;deleteButton.disabled=false;}
      });
      if(message.quarantine_reason){
        const release=node('button','Release to inbox','secondary');release.type='button';
        release.addEventListener('click',async()=>{
          release.disabled=true;
          try{await request('/api/v1/admin/contact-messages/'+message.id+'/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'release'})});await loadContacts();}
          catch(e){$('contact-unread-status').textContent=e.message;release.disabled=false;}
        });
        actions.append(release,deleteButton);
      }else actions.append(readButton,archiveButton,replyButton,deleteButton);
      content.append(actions);item.append(content);$('site-contact-list').append(item);
    }
    contactOffset+=p.messages.length;
    $('site-contact-more').hidden=!p.has_more;
  }catch(e){
    $('contact-unread-status').textContent='Unable to load native submissions: '+e.message;
    $('contact-unread-count').textContent='unavailable';
    $('site-contact-disclosure').open=true;
    $('site-contact-more').hidden=true;
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

// Local hide/restore: provider messages remain on Resend under its retention policy.
const incomingToggle=node('label');
const showHidden=node('input');showHidden.type='checkbox';showHidden.id='incoming-show-hidden';
incomingToggle.append(showHidden,document.createTextNode(' Show hidden messages'));
$('incoming-status').insertAdjacentElement('afterend',incomingToggle);

async function loadIncoming(){
  $('incoming-disclosure').open=true;
  $('incoming-status').textContent='Checking Resend incoming mail…';
  $('incoming-list').replaceChildren();
  $('incoming-check').disabled=true;
  try{
    const response=await request('/api/v1/admin/mail/incoming?limit=30&include_hidden='+(showHidden.checked?'true':'false'));
    if(!response.configured){$('incoming-status').textContent='Resend receiving is not configured.';return;}
    $('incoming-status').textContent=`${response.messages.length} emails shown from the latest provider page. Hidden emails remain at Resend until its retention period expires.`;
    for(const item of response.messages){
      const container=node('details',undefined,'contact-message');
      const summary=node('summary',`${item.hidden?'[Hidden] ':''}${item.subject||'(No subject)'} · ${item.from||'Unknown sender'} · ${(item.created_at||'').slice(0,16)}`);
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
      const actions=node('div',undefined,'action-row');
      const btn=node('button',item.hidden?'Restore':'Delete','secondary');btn.type='button';
      btn.addEventListener('click',async()=>{
        if(!item.hidden&&!window.confirm('Hide this incoming email from Gnosis Admin? This does NOT delete the message from Resend. You can restore it with Show hidden messages.'))return;
        btn.disabled=true;
        try{await request('/api/v1/admin/mail/incoming/'+encodeURIComponent(item.id)+'/visibility',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:item.hidden?'restore':'hide'})
        });await loadIncoming();}
        catch(e){$('incoming-status').textContent=e.message;btn.disabled=false;}
      });
      actions.append(btn);content.append(t,body,actions);container.append(summary,content);$('incoming-list').append(container);
    }
  }catch(e){$('incoming-status').textContent=e.message;
  }finally{$('incoming-check').disabled=false;}
}
$('incoming-check')?.addEventListener('click',loadIncoming);
showHidden.addEventListener('change',loadIncoming);

loadContacts();
loadMailConfig();
