const $ = id => document.getElementById(id);
const limit = 25;
let offset = 0;
function el(tag, klass, content) {
  const item = document.createElement(tag);
  if (klass) item.className = klass;
  if (content !== undefined) item.textContent = String(content);
  return item;
}
async function loadHistory() {
  $('history-status').textContent='Loading readings…';
  const response=await fetch(`/api/v1/accounts/readings?limit=${limit}&offset=${offset}`,{
    credentials:'same-origin',cache:'no-store'
  });
  if (response.status===401) {
    $('history-status').replaceChildren(document.createTextNode('Sign in on the '));
    const a=el('a',null,'Account page'); a.href='/account.html'; $('history-status').append(a);
    $('history-list').replaceChildren();return;
  }
  if (!response.ok) throw new Error(`History unavailable (${response.status})`);
  const body=await response.json();
  const list=$('history-list');list.replaceChildren();
  for (const reading of body.items) {
    const card=el('article','history-item');
    const title=el('h2',null,reading.provider==='qci'?'QCI quantum reading':reading.service_id);
    const link=el('a',null,'Open in Oracle');
    link.href=`/quantum-oracle.html?reading=${encodeURIComponent(reading.consultation_id)}`;
    title.prepend(link,document.createTextNode(' · '));
    card.append(title);
    card.append(el('p','meta',`${new Date(reading.finished_at).toLocaleString()} · ${reading.moving_count} moving lines · ${reading.provider}`));
    card.append(el('p','question',reading.question || '(No question entered)'));
    card.append(el('p','meta',`Line values, bottom to top: ${reading.lines.join(', ')}`));
    list.append(card);
  }
  $('history-status').textContent=body.total?`${body.total} saved reading${body.total===1?'':'s'}`:'No saved server-backed readings yet.';
  $('history-prev').disabled=offset===0;
  $('history-next').disabled=offset+body.items.length>=body.total;
  $('history-page').textContent=`${body.total?offset+1:0}–${offset+body.items.length} of ${body.total}`;
}
async function refresh() {
  try{await loadHistory();}catch(error){$('history-status').textContent=error.message;}
}
$('history-prev').addEventListener('click',()=>{offset=Math.max(0,offset-limit);void refresh();});
$('history-next').addEventListener('click',()=>{offset+=limit;void refresh();});
void refresh();
