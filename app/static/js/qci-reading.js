const get=id=>document.getElementById(id);
const status=get('status');
const id=new URLSearchParams(location.search).get('id');
function draw(container,values){
  container.replaceChildren();
  for(const value of [...values].reverse()){
    const el=document.createElement('div');
    el.className='line '+(value?'yang':'yin');
    el.setAttribute('aria-label',value?'Solid yang':'Broken yin');
    container.append(el);
  }
}
async function load(){
  if(!id||!/^[a-f0-9]{32}$/.test(id)) throw Error('Invalid consultation ID');
  const r=await fetch('/api/v1/consultations/'+encodeURIComponent(id),{credentials:'same-origin',cache:'no-store'});
  if(r.status===401)throw Error('Please sign in at /account.html before viewing this reading');
  if(!r.ok)throw Error('Reading not found or unavailable');
  const receipt=await r.json();
  if(receipt.status==='pending') {status.textContent='Reading is still pending. Reload this page to check again.';return;}
  if(receipt.status!=='completed'||!receipt.result)throw Error('This consultation did not produce a complete reading');
  const reading=receipt.result.reading;
  const provenance=receipt.result.provenance;
  if(!Array.isArray(reading.lines)||reading.lines.length!==6)throw Error('Invalid stored reading');
  get('question').textContent=receipt.question ? 'Your question: '+receipt.question : 'Open inquiry';
  draw(get('now'),reading.now_yang_bits_bottom_to_top);
  draw(get('becoming'),reading.becoming_yang_bits_bottom_to_top);
  get('moving').textContent=reading.moving_positions_bottom_to_top.length
    ? 'Moving lines (bottom to top): '+reading.moving_positions_bottom_to_top.join(', ')
    : 'No moving lines';
  get('lines').textContent=reading.lines.map((v,i)=>`Line ${i+1}: ${v} · coins ${reading.coin_bits_bottom_to_top[i]}`).join('\n');
  get('provenance').textContent=JSON.stringify(provenance,null,2);
  get('result').hidden=false;
  status.textContent=provenance.provider==='nist' ? 'Complete · NIST Public Beacon · 0 credits charged' : 'Complete · QCI uQRNG · 0 credits charged';
}
load().catch(error=>{status.textContent=error.message;status.classList.add('error');});
