// Private editor. No innerHTML, no external scripts, no draft autosave. Corpus-wide releases only.
const $=id=>document.getElementById(id);
const make=(tag,txt,cls)=>{const e=document.createElement(tag);if(txt!==undefined)e.textContent=txt;if(cls)e.className=cls;return e;};
const LABELS={title:'Title',essence:'Essence',archetypal_meaning:'Archetypal meaning',
 historical_core:'Historical context',modern_meaning:'Modern interpretation',advice:'Further guidance',
 shadow:'Shadow / pitfalls',reflection_question:'Reflection question',interpretation:'Interpretation',reflection:'Reflection'};
let catalog=[],activeNumber=1,activeTradition='taoist',record=null,dirty=false,editValues={};
async function api(url,options={}){
  const resp=await fetch('/api/v1/admin/editor'+url,{credentials:'same-origin',cache:'no-store',...options});
  if(!resp.ok){let info;try{info=await resp.json()}catch{};throw new Error(info?.detail||`Request failed (${resp.status})`)}
  return resp.json();
}
const message=s=>{$('editor-feedback').textContent=s;};
const titleCase=s=>LABELS[s]||s.replaceAll('_',' ').replace(/\b\w/g,x=>x.toUpperCase());
function setDirty(){dirty=activeTradition==='classical'?false:Object.keys(editValues).some(k=>editValues[k]!==record.editable_current[k]);
  $('unsaved-hint').textContent=dirty?'Unsaved changes':'';
  const classical=activeTradition==='classical';
  $('save-draft').disabled=classical||!dirty;
  if(dirty)$('publish-release').disabled=true;
  $('mark-reviewed').disabled=dirty||Boolean(record.reviewed_at);
  $('approve-record').disabled=dirty||!record.reviewed_at||Boolean(record.approved_at);
  $('unapprove-record').disabled=dirty||!record.approved_at;
}
function updateStatus(){
  if(!record)return;
  const stats=[`Published corpus v${record.corpus_version}`,
    record.revision?'Private edit '+record.revision.slice(0,8):'No private edits',
    record.reviewed_at?'Reviewed '+record.reviewed_at.slice(0,10):'Not reviewed',
    record.approved_at?'Explicitly approved '+record.approved_at.slice(0,10):'Approval pending',
    record.published_approved?'Published approval: yes':'Published approval: no'];
  $('editor-meta').replaceChildren(...stats.map(s=>make('span',s)));
}
async function loadCatalog(q=''){
  const p=await api('/catalog?q='+encodeURIComponent(q));
  catalog=p.hexagrams;
  $('editor-progress').replaceChildren(...['classical','taoist','confucian'].map(t=>{
    const x=p.progress[t];const node=make('div',undefined,'editor-stat');
    node.append(make('strong',`${x.approved}/64 approved`),
      make('span',`${titleCase(t)} · ${x.reviewed} reviewed · ${x.drafted} drafted${x.stale?' · '+x.stale+' stale':''}`));
    return node;
  }));
  const totals=Object.values(p.progress).reduce((n,v)=>n+v.approved,0);
  $('editor-progress').append(make('div',`${totals}/192 approved · draft workspace only`,'editor-stat'));
  $('hex-list').replaceChildren(...catalog.map(r=>{
    const e=make('button',undefined,'hex-choice'+(r.number===activeNumber?' selected':''));
    e.type='button';e.append(make('span',`${String(r.number).padStart(2,'0')} · ${r.symbol} ${r.title||'—'}`),
      make('small',`${r.chinese} · ${r.pinyin}`));
    e.addEventListener('click',()=>select(r.number,activeTradition));return e;
  }));
}
function appendField(parent,key,value,editable=true){
  const e=make('div',undefined,'editor-field');
  const label=make('label',titleCase(key.split('.').at(-1)));e.append(label);
  if(editable){
    const short=key==='title';
    const input=make(short?'input':'textarea');
    input.id='field-'+key.replaceAll('.','-');label.htmlFor=input.id;
    input.value=value;input.maxLength=20000;
    if(!short){input.rows=value.length>500?9:4;if(value.length>500)input.classList.add('long')}
    input.addEventListener('input',()=>{
      editValues[key]=input.value;
      e.classList.toggle('changed',input.value!==record.editable_original[key]);
      setDirty();renderPreview();
    });
    e.classList.toggle('changed',value!==record.editable_original[key]);
    e.append(input);
  }else e.append(make('p',value,'editor-readonly'));
  parent.append(e);
}
function renderFields(){
  $('editor-fields').replaceChildren();
  const root=$('editor-fields');
  if(activeTradition==='classical'){
    root.append(make('p','Classical source and translation fields are protected. You may review and approve this tradition without changing its text.','editor-notice'));
    const o=record.record.classical;
    for(const k of ['judgment_zh','judgment_en','image_zh','image_en','historical_note'])
      if(typeof o[k]==='string')appendField(root,k,o[k],false);
    const group=make('details',undefined,'editor-line-group');group.open=true;group.append(make('summary','Classical lines (read only)'));
    const body=make('div',undefined,'editor-line-items');
    for(const line of o.lines){const cell=make('div',undefined,'editor-line');
      cell.append(make('h3',`Line ${line.position}`));
      for(const k of ['label_zh','text_zh','translation_en'])if(line[k])appendField(cell,k,line[k],false);
      body.append(cell)}
    group.append(body);root.append(group);
    if(o.special)root.append(make('p','Special use-nine/use-six passage is source-protected (read only).','editor-readonly'));
    return;
  }
  editValues={...record.editable_current};
  for(const key of ['title','essence','archetypal_meaning','historical_core','modern_meaning','advice','shadow','reflection_question']){
    if(key in editValues)appendField(root,key,editValues[key]);
  }
  const lines=make('details',undefined,'editor-line-group');lines.open=true;
  lines.append(make('summary','Six moving-line interpretations and reflections'));
  const list=make('div',undefined,'editor-line-items');
  for(let i=0;i<6;i++){
    const item=make('div',undefined,'editor-line');item.append(make('h3','Line '+(i+1)+' · bottom to top'));
    for(const name of ['interpretation','reflection']){
      const key=`lines.${i}.${name}`;if(key in editValues)appendField(item,key,editValues[key]);
    }
    list.append(item);
  }
  lines.append(list);root.append(lines);
  const specials=Object.keys(editValues).filter(k=>k.startsWith('special.'));
  if(record.record[activeTradition].special){
    const g=make('details',undefined,'editor-line-group');
    g.append(make('summary','Special use-nine/use-six passage'));
    const b=make('div',undefined,'editor-line-items');
    for(const key of specials)appendField(b,key,editValues[key]);
    if(!specials.length)b.append(make('p','This special passage contains no explicitly allowlisted modern editorial fields. Original text and evidence remain read-only.','editor-readonly'));
    g.append(b);root.append(g);
  }
}
function renderPreview(snapshot=null){
  if(!record)return;
  const view=$('editor-preview'),diff=$('editor-diff');view.replaceChildren();diff.replaceChildren();
  const shown=snapshot||editValues;
  if(activeTradition==='classical'){
    view.append(make('p','Classical materials are unchanged in the public corpus. Review and approval can be recorded here.'));
    return;
  }
  // These same named fields feed the public reading's textual presentation.
  const fields=['modern_meaning','reflection_question','historical_core','advice','shadow','essence','archetypal_meaning'];
  for(const k of fields){if(!(k in shown))continue;
    const item=make('div',undefined,'editor-preview-item');
    item.append(make('h4',titleCase(k)),make('p',shown[k]));view.append(item);
  }
  const changed=Object.keys(shown).filter(k=>shown[k]!==record.editable_original[k]);
  diff.append(make('h3',changed.length?`${changed.length} changed fields vs. current published text`:'No changes to published text'));
  for(const k of changed){const item=make('div',undefined,'editor-change');item.append(make('h4',k.replaceAll('.',' / ')));
    const compare=make('div',undefined,'editor-change-comparison');
    const before=make('div',undefined,'before'),after=make('div',undefined,'after');
    before.append(make('strong','PUBLISHED'),make('span',record.editable_original[k]));
    after.append(make('strong','DRAFT'),make('span',shown[k]));
    compare.append(before,after);item.append(compare);diff.append(item);
  }
}
function renderHistory(){
  const parent=$('editor-history-list');parent.replaceChildren();
  if(!record.history.length){parent.append(make('p','No editorial drafts yet.'));return;}
  for(const h of record.history){const row=make('div',undefined,'editor-history-row');
    row.append(make('span',`${h.at} · ${h.action} · ${h.actor.slice(0,12)} · ${h.changed_fields.length} fields`));
    const actions=make('div');
    const compare=make('button','Compare');compare.type='button';
    compare.addEventListener('click',async()=>{try{
      const revision=await api(`/record/${activeNumber}/${activeTradition}/history/${h.id}`);
      renderPreview(revision.fields);$('editor-compare').open=true;
      message('Viewing historical revision in the preview. It is NOT loaded into your editing fields.');
    }catch(e){message(e.message)}});
    actions.append(compare);
    const restore=make('button','Restore as new draft');restore.type='button';
    restore.addEventListener('click',()=>operate('restore',h.id));
    actions.append(restore);row.append(actions);parent.append(row);
  }
}
async function select(number,tradition){
  if(dirty&&!confirm('Discard unsaved changes to this draft?'))return;
  activeNumber=number;activeTradition=tradition;record=null;dirty=false;
  message('Loading interpretation…');
  try{record=await api(`/record/${number}/${tradition}`);
    $('record-title').textContent=`${String(number).padStart(2,'0')} · ${record.record.symbol} ${record.record[tradition]?.title||record.record.taoist.title}`;
    $('record-subtitle').textContent=`${record.record.chinese} · ${record.record.pinyin} · ${titleCase(tradition)}`;
    for(const b of document.querySelectorAll('[data-tradition]'))b.classList.toggle('active',b.dataset.tradition===tradition);
    editValues={...record.editable_current};updateStatus();renderFields();setDirty();renderPreview();renderHistory();message('Draft workspace ready. Published readings are unaffected.');
    for(const b of document.querySelectorAll('.hex-choice'))b.classList.toggle('selected',Number(b.textContent.slice(0,2))===number);
  }catch(e){message(e.message);$('editor-fields').replaceChildren();}
}
async function saveDraft(){
  if(!record||!dirty||activeTradition==='classical')return;
  const fields={...editValues};
  const number=activeNumber,tradition=activeTradition,head=record.revision;
  message('Saving new private draft revision…');$('save-draft').disabled=true;
  try{
    const result=await api(`/record/${number}/${tradition}/draft`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({expected_head:head,fields})});
    // Saving is NOT confirmed by a 200 alone. Verify the revision ID and
    // all edited fields with a fresh authenticated read from persistent state.
    const verified=await api(`/record/${number}/${tradition}`);
    if(verified.revision!==result.revision ||
       Object.keys(fields).some(k=>verified.editable_current[k]!==fields[k])){
      throw new Error('Save not verified: server did not return the exact saved revision and text. Keep this tab open; do not re-submit blindly.');
    }
    if(number!==activeNumber||tradition!==activeTradition)
      throw new Error('Selected record changed during save; reload before editing further.');
    record=verified;
    editValues={...verified.editable_current};
    dirty=false;updateStatus();renderFields();setDirty();renderPreview();renderHistory();
    message(`Draft saved and verified · revision ${verified.revision?.slice(0,12)||'unchanged'}. Published corpus not changed.`);
    loadCatalog($('hex-search').value).catch(e=>message('Saved and verified; search refresh failed: '+e.message));
    loadReleasePreview().catch(e=>message('Saved and verified; release preview failed: '+e.message));
  }catch(e){
    // Preserve all entered text; an unknown network result may have reached
    // the server. Never pretend failure means the write was rolled back.
    message('SAVE NOT VERIFIED: '+e.message+' · Your typed edits remain in this tab.');
    setDirty();
  }
}
async function operate(action,revision_id=null){
  if(!record||dirty){message('Save or discard unsaved changes before changing review state.');return;}
  if(action==='approve'&&!confirm('Explicitly approve this editorial record? This marks the private review record approved, but does NOT publish it.'))return;
  if(action==='restore'&&!confirm('Restore selected historical text as a NEW draft? Current history is preserved; review/approval will reset.'))return;
  try{await api(`/record/${activeNumber}/${activeTradition}/action`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action,expected_head:record.revision,revision_id})});
    await select(activeNumber,activeTradition);await loadCatalog($('hex-search').value);
    message(action==='approve'?'Record explicitly approved in private workspace. No publication occurred.':'Editorial state updated.');await loadReleasePreview();
  }catch(e){message(e.message)}
}
$('save-draft').addEventListener('click',saveDraft);
$('mark-reviewed').addEventListener('click',()=>operate('review'));
$('approve-record').addEventListener('click',()=>operate('approve'));
$('unapprove-record').addEventListener('click',()=>operate('unapprove'));
for(const button of document.querySelectorAll('[data-tradition]'))
  button.addEventListener('click',()=>select(activeNumber,button.dataset.tradition));
let searchTimer;
$('hex-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadCatalog($('hex-search').value).catch(e=>message(e.message)),250)});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
loadCatalog().then(()=>select(1,'taoist')).catch(e=>message(e.message));


// Global corpus release history; this is the only externally visible versioning.
let releasePlan=null;
async function loadReleasePreview(){
  $('publish-release').disabled=true;
  $('release-status').textContent='Validating entire 64-hexagram release…';
  try{
    const p=await api('/publication/preview');releasePlan=p;
    $('release-preview').replaceChildren();
    const summary=make('p',`Current corpus v${p.version_before} · Proposed v${p.version_after} · ${p.changed_fields} changed fields in ${p.changed_records} records · ${p.new_approvals} new approvals · ${p.unapproved_drafts_excluded} unapproved drafts excluded`);
    const hashes=make('p',`Before SHA-256: ${p.before_sha256} · After SHA-256: ${p.after_sha256||'Unavailable'}`);
    hashes.className='release-hash';
    $('release-preview').append(summary,hashes);
    if(p.hash_basis){
      $('release-preview').append(make('p',
        `${p.hash_basis}. ${p.hash_matches}/192 inherited hashes also match the site-content formula; nonmatches do not invalidate the verified original corpus.`,
        'editor-notice'));
    }
    if(p.reasons?.length){for(const reason of p.reasons)$('release-preview').append(make('p',reason,'editor-notice'));}
    $('release-status').textContent=p.can_publish?
      (p.enabled?'Ready to publish the validated complete corpus.':'Preview valid; publication remains disabled by server configuration.'):
      'Publication blocked until all preflight requirements are satisfied.';
    $('publish-release').textContent=`Publish corpus v${p.version_after}`;
    $('publish-release').disabled=!p.can_publish||!p.enabled||dirty;
    renderReleaseHistory(p.latest_publications||[]);
  }catch(e){releasePlan=null;$('release-status').textContent=e.message;}
}
function renderReleaseHistory(list){
  const host=$('release-history');host.replaceChildren();
  if(!list?.length){host.append(make('p','No site publications recorded through this editor.'));return;}
  for(const r of list){const card=make('details',undefined,'editor-history-row');
    card.append(make('summary',`${r.version_before} → ${r.version_after} · ${r.published_utc} · ${r.status} · ${r.changed_fields} field changes`));
    const details=make('div',undefined,'release-details');
    details.append(make('p',`Administrator: ${r.actor||'unknown'}`),
      make('p',`Before SHA-256: ${r.before_sha256}`),make('p',`After SHA-256: ${r.after_sha256}`));
    let loaded=false;
    card.addEventListener('toggle',async()=>{
      if(!card.open||loaded)return;loaded=true;
      try{const d=await api('/publication/history/'+encodeURIComponent(r.release_id));
        if(!d.field_changes?.length)details.append(make('p','No text changes in this release (approval-only).'));
        for(const f of d.field_changes){
          const item=make('div',undefined,'editor-change');
          item.append(make('h4',`Hexagram ${f.number} · ${f.tradition} · ${f.field}`));
          const comparison=make('div',undefined,'editor-change-comparison');
          const before=make('div',undefined,'before'),after=make('div',undefined,'after');
          before.append(make('strong','PREVIOUS RELEASE'),make('span',f.before));
          after.append(make('strong','PUBLISHED'),make('span',f.after));
          comparison.append(before,after);item.append(comparison);details.append(item);
        }
      }catch(e){details.append(make('p',e.message));}
    });
    card.append(details);host.append(card);
  }
}
$('preview-release').addEventListener('click',loadReleasePreview);
$('publish-release').addEventListener('click',async()=>{
  if(!releasePlan?.can_publish||!releasePlan?.enabled)return;
  if(dirty){$('release-status').textContent='Save or discard your unsaved edits first.';return;}
  if(!confirm(`Publish complete I Ching corpus v${releasePlan.version_after}?\n\n`+
     `${releasePlan.changed_fields} field changes; ${releasePlan.new_approvals} newly approved records.\n`+
     'This updates the live interpretation corpus and records a timestamped version event.'))return;
  $('publish-release').disabled=true;$('release-status').textContent='Applying the verified full-corpus release…';
  try{
    const result=await api('/publication/publish',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({expected_plan_token:releasePlan.plan_token})});
    $('release-status').textContent=`Published v${result.version} at ${result.published_utc}. Before ${result.before_sha256} · After ${result.after_sha256}`;
    await loadCatalog($('hex-search').value);
    await select(activeNumber,activeTradition);
    await loadReleasePreview();
  }catch(e){$('release-status').textContent=e.message;await loadReleasePreview();}
});
loadReleasePreview();
