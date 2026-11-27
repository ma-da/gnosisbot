// First-party contact form; timing is enforced by the server, not this UI.
const form=document.getElementById('contact-form');
const status=document.getElementById('contact-native-status');
if(form&&status){
  const send=form.querySelector('button[type="submit"]');
  let ticket=null, pending=null, ready=0, expiry=0, timer=null, busy=false;
  const show=s=>{status.hidden=false;status.textContent=s;};
  function refresh(){
    clearTimeout(timer);
    if(busy){send.disabled=true;return;}
    if(!ticket){send.disabled=false;return;}
    const remaining=Math.ceil((ready-performance.now())/1000);
    send.disabled=remaining>0;
    if(remaining>0){show(`Please wait ${remaining} seconds before sending.`);timer=setTimeout(refresh,250);}
    else if(status.textContent.startsWith('Please wait '))show('You can now send your message.');
  }
  async function initialize(){
    if(ticket&&performance.now()<expiry)return;
    if(pending)return pending;
    ticket=null;
    pending=(async()=>{
      const r=await fetch('/api/v1/contact/token',{method:'POST',credentials:'same-origin',cache:'no-store'});
      if(!r.ok)throw new Error('Contact form temporarily unavailable. Try again.');
      const d=await r.json();
      if(typeof d.token!=='string'||!Number.isFinite(d.minimum_seconds)||!Number.isFinite(d.expires_in))throw new Error('Contact form unavailable.');
      ticket=d.token;ready=performance.now()+d.minimum_seconds*1000;expiry=performance.now()+d.expires_in*1000-2000;
    })();
    try{await pending;}finally{pending=null;refresh();}
  }
  send.disabled=false;
  form.addEventListener('focusin',()=>{if(!busy)initialize().catch(e=>show(e.message));});
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(busy||!form.reportValidity())return;
    busy=true;refresh();
    try{
      await initialize();
      if(performance.now()<ready){show('Please wait before sending.');return;}
      const fields=new FormData(form);
      const body={name:String(fields.get('name')||''),email:String(fields.get('email')||''),message:String(fields.get('message')||''),website:String(fields.get('website')||''),token:ticket};
      const encoded=JSON.stringify(body);
      if(new TextEncoder().encode(encoded).length>8192)throw new Error('Message is too long. Please shorten it.');
      show('Sending your message…');
      const response=await fetch('/api/v1/contact',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','Accept':'application/json'},body:encoded});
      const d=await response.json().catch(()=>({}));
      if(!response.ok){
        if(response.status===425){ready=performance.now()+Math.max(1,Number(d.retry_after)||1)*1000;return;}
        if(response.status===403){ticket=null;await initialize();return;}
        if(response.status===409){ticket=null;throw new Error('This form was already used. Your previous message may have been received. Check before sending again.');}
        throw new Error(typeof d.detail==='string'?d.detail:`Message not sent (${response.status}).`);
      }
      if(d.received!==true)throw new Error('Receipt not confirmed. Please check before retrying.');
      ticket=null;form.reset();show('Thank you. Your message has been received.');
    }catch(e){show(e instanceof Error?e.message:'Unable to send your message.');}
    finally{busy=false;refresh();}
  });
}
