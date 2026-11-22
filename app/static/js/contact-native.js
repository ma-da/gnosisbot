// Progressive cutover: Formspree remains the no-JS / disabled-native fallback.
// Once GNOSIS_ENABLE_NATIVE_CONTACTS=1 is tested, JS submissions go to Gnosis.
const form=document.getElementById('contact-form');
if(form){
  const status=document.createElement('p');
  status.id='contact-native-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  form.append(status);
  form.addEventListener('submit',async(event)=>{
    event.preventDefault();
    const submit=form.querySelector('button[type=submit]');
    if(submit)submit.disabled=true;
    status.textContent='Sending your message…';
    try{
      const health=await fetch('/api/v1/contact/status',{credentials:'same-origin',cache:'no-store'});
      if(!health.ok || !(await health.json()).available){
        status.textContent='';
        form.submit(); // Preserve existing Formspree path until native is enabled.
        return;
      }
      const info=new FormData(form);
      const body={name:info.get('name'),email:info.get('email'),message:info.get('message'),website:info.get('website')||''};
      const result=await fetch('/api/v1/contact',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
      if(!result.ok)throw new Error('Message could not be saved ('+result.status+'). Please retry later.');
      form.reset();status.textContent='Message received. Thank you for writing.';
    }catch(error){
      // Never auto-submit to Formspree on an ambiguous native error: might double-send.
      status.textContent=error.message||'Message unavailable; please try later.';
    }finally{if(submit)submit.disabled=false;}
  });
}
