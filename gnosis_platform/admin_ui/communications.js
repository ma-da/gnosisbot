/* Gnosis Communications V0.4 — admin-only drafts, publish and archive.
 * Audience enforcement lives exclusively on server; never build HTML from message text.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const root=$('communications');
  if (!root) return;
  const form=$('comms-form');
  const feedback=$('comms-feedback');
  const list=$('comms-items');
  let entries=[];
  let selected=null;
  let busy=false;
  function node(tag,content,klass){const el=document.createElement(tag);if(content!==undefined)el.textContent=content;if(klass)el.className=klass;return el;}
  function say(s, error=false){feedback.textContent=s;feedback.dataset.error=String(error);}
  async function api(url,options={}){
    const res=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{})},...options});
    const data=await res.json().catch(()=>({}));
    if(!res.ok)throw new Error(data.detail || `Request unavailable (${res.status})`);
    return data;
  }
  const itemText = item => `${item.audience_kind === 'all' ? 'Everyone' : item.audience_kind === 'group' ? 'Group: '+item.audience_value : 'Account: '+item.audience_value}`;
  async function loadGroups(){
    try{
      const data=await api('/api/v1/admin/communications/groups');
      const sel=$('comms-group');
      const old=sel.value;
      sel.replaceChildren();
      const empty=node('option','Select a group');empty.value='';sel.append(empty);
      for (const g of data.groups||[]){const opt=node('option',g);opt.value=g;sel.append(opt);}
      if([...sel.options].some(x=>x.value===old))sel.value=old;
    }catch(e){say('Unable to load account groups: '+e.message,true);}
  }
  function audience(){
    const kind=$('comms-audience').value;
    $('comms-group-label').hidden=kind!=='group';
    $('comms-account-label').hidden=kind!=='account';
    $('comms-group').required=kind==='group';
    $('comms-account').required=kind==='account';
  }
  function reset(){selected=null;form.reset();$('comms-save').textContent='Save draft';$('comms-cancel').hidden=true;audience();}
  function edit(item){
    if(item.status!=='draft')return;
    selected=item;
    form.elements.namedItem('title').value=item.title;
    form.elements.namedItem('body').value=item.body;
    $('comms-audience').value=item.audience_kind;
    $('comms-group').value=item.audience_kind==='group'?item.audience_value:'';
    $('comms-account').value=item.audience_kind==='account'?item.audience_value:'';
    form.elements.namedItem('action_label').value=item.action_label;
    form.elements.namedItem('action_href').value=item.action_href;
    form.elements.namedItem('allow_reply').checked=Boolean(item.allow_reply);
    $('comms-save').textContent='Update draft';$('comms-cancel').hidden=false;
    audience();form.elements.namedItem('title').focus();
  }
  async function change(item, action){
    if(busy)return;
    const warning=action==='publish'?`Publish “${item.title}” to ${itemText(item)}? Recipients will see it immediately. Published messages cannot be edited.`:`Archive “${item.title}”? This hides it from accounts.`;
    if(!window.confirm(warning))return;
    busy=true;say('Updating message…');
    try{
      await api(`/api/v1/admin/communications/${item.notice_id}/${action}`,{method:'POST',body:JSON.stringify({revision:item.revision})});
      reset();await refresh();say(action==='publish'?'Message published.':'Message archived.');
    }catch(e){say(e.message,true);await refresh();}
    finally{busy=false;}
  }
  function draw(){
    list.replaceChildren();
    if(!entries.length){list.append(node('p','No account messages yet. Create a draft above.','comms-empty'));return;}
    for(const item of entries){
      const row=node('article',undefined,'comms-item');
      const heading=node('div',undefined,'comms-item-heading');
      heading.append(node('strong',item.title),node('span',item.status,'comms-state'));
      row.append(heading,node('p',itemText(item),'comms-meta'));
      row.append(node('p',item.body.length>240?item.body.slice(0,240)+'…':item.body,'comms-body'));
      if(item.action_href)row.append(node('p',`Action: ${item.action_label} — ${item.action_href}`,'comms-meta'));
      if(item.allow_reply)row.append(node('p','Replies enabled · sent to original author’s account inbox','comms-meta'));
      const actions=node('div',undefined,'comms-actions');
      if(item.status==='draft'){
        const b=node('button','Edit draft');b.type='button';b.className='secondary';b.addEventListener('click',()=>edit(item));actions.append(b);
        const pub=node('button','Publish');pub.type='button';pub.addEventListener('click',()=>change(item,'publish'));actions.append(pub);
      }
      if(item.status!=='archived'){
        const archive=node('button','Archive');archive.type='button';archive.className='secondary';archive.addEventListener('click',()=>change(item,'archive'));actions.append(archive);
      }
      row.append(actions);list.append(row);
    }
  }
  async function refresh(){
    const archived=$('comms-show-archived')?.checked===true;
    const data=await api('/api/v1/admin/communications?limit=40&offset=0&include_archived='+archived);
    entries=data.items||[];
    draw();
    $('comms-total').textContent=`Showing ${entries.length} of ${data.total||0}`;
  }
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;
    const kind=$('comms-audience').value;
    const data={
      title:form.elements.namedItem('title').value.trim(),
      body:form.elements.namedItem('body').value.trim(),
      audience_kind:kind,
      audience_value:kind==='group'?$('comms-group').value:kind==='account'?$('comms-account').value.trim():'',
      action_label:form.elements.namedItem('action_label').value.trim(),
      action_href:form.elements.namedItem('action_href').value.trim(),
      allow_reply:form.elements.namedItem('allow_reply').checked,
      revision:selected?.revision??null
    };
    busy=true;$('comms-save').disabled=true;say('Saving draft…');
    try{
      await api(selected?`/api/v1/admin/communications/${selected.notice_id}`:'/api/v1/admin/communications',
        {method:selected?'PUT':'POST',body:JSON.stringify(data)});
      reset();await refresh();say('Draft saved. Publish separately when ready.');
    }catch(err){say(err.message,true);await refresh();}
    finally{busy=false;$('comms-save').disabled=false;}
  });
  $('comms-cancel').addEventListener('click',()=>reset());
  $('comms-show-archived').addEventListener('change',()=>refresh().catch(e=>say(e.message,true)));
  $('comms-refresh').addEventListener('click',async()=>{
    try{await loadGroups();await refresh();say('Messages refreshed.');}catch(e){say(e.message,true);}
  });
  $('comms-audience').addEventListener('change',audience);
  audience();
  Promise.all([loadGroups(),refresh()]).then(()=>say('Communications ready. Drafts are not visible to recipients.')).catch(e=>say('Messages unavailable: '+e.message,true));
})();
