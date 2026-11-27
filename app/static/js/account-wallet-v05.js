/** Gnosis wallet V0.5: no wallet provider access/discovery until user clicks Connect. */
const $ = id => document.getElementById(id);
const connectButton = $('gnosis-wallet-connect');
const linkedBox = $('gnosis-wallet-linked');
const initialBox = $('gnosis-wallet-unlinked');
const statusBox = $('gnosis-wallet-registration-status');
const addressBox = $('gnosis-wallet-address');
const solBox = $('gnosis-wallet-sol');
const rstoryBox = $('gnosis-wallet-rstory');
const balanceStamp = $('gnosis-wallet-balance-timestamp');
const unlinkButton = $('gnosis-wallet-unlink');
const refreshButton = $('gnosis-wallet-refresh');
const copyButton = $('gnosis-wallet-copy');
const modal = $('gnosis-wallet-picker');
const choices = $('gnosis-wallet-picker-choices');
const closeModal = $('gnosis-wallet-picker-close');
const B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
let generation=0;
let address=null;
let busy=false;
const signedIn=()=>document.body.dataset.gnosisSession==='authenticated';
const setStatus=(message,error=false)=>{if(statusBox){statusBox.textContent=message;statusBox.dataset.error=String(error);}};

async function api(path, options={}) {
  const res=await fetch('/api/v1/accounts/wallet'+path,{
    credentials:'same-origin', cache:'no-store',
    headers:{'Accept':'application/json',...(options.body?{'Content-Type':'application/json'}:{})},
    ...options,
  });
  const data=await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(typeof data.detail==='string' ? data.detail : `Wallet request failed (${res.status})`);
  return data;
}

function encodeBase58(bytes) {
  const raw=Uint8Array.from(bytes);
  if(raw.length!==64)throw new Error('Wallet returned an invalid signature length');
  let value=0n;
  for(const b of raw)value=(value<<8n)+BigInt(b);
  let result='';
  while(value>0n){result=B58[Number(value%58n)]+result;value/=58n;}
  let zeros=0;
  while(zeros<raw.length && raw[zeros]===0)zeros++;
  return '1'.repeat(zeros)+result;
}

function reset() {
  ++generation;
  address=null;
  if(initialBox)initialBox.hidden=false;
  if(linkedBox)linkedBox.hidden=true;
  if(addressBox)addressBox.textContent='—';
  if(solBox)solBox.textContent='—';
  if(rstoryBox)rstoryBox.textContent='—';
  if(balanceStamp)balanceStamp.textContent='Balances not loaded';
  setStatus('');
  if(modal?.open)modal.close();
}

function showLinked(data) {
  address=data.address;
  initialBox.hidden=true;
  linkedBox.hidden=false;
  addressBox.textContent=address;
  addressBox.title=address;
  setStatus('Linked wallet ownership verified by signed message.');
}

async function loadBalances() {
  if(!address||!signedIn())return;
  const expected=address;
  solBox.textContent='—';rstoryBox.textContent='—';
  balanceStamp.textContent='Refreshing public on-chain balances…';
  try {
    const data=await api('/balances');
    if(expected!==address||!signedIn())return;
    if(data.address!==address||data.status!=='ok'){
      balanceStamp.textContent='Balances unavailable. Registration remains verified.';
      return;
    }
    solBox.textContent=data.sol;
    rstoryBox.textContent=data.rstory;
    balanceStamp.textContent=`Solana mainnet · Checked ${new Date(data.as_of).toLocaleString()}`;
  } catch {
    if(expected===address)balanceStamp.textContent='Balances temporarily unavailable.';
  }
}

async function sync() {
  const epoch=++generation;
  if(!signedIn()){reset();return;}
  try {
    const data=await api(''); // Public Gnosis DB status only; NO browser-wallet interaction.
    if(epoch!==generation||!signedIn())return;
    if(data.linked && data.address){showLinked(data);void loadBalances();return;}
    address=null;
    initialBox.hidden=false;linkedBox.hidden=true;
    connectButton.disabled=!data.enabled;
    setStatus(data.enabled?'Connect a wallet to verify public address ownership. No transaction or fee.':
      'Wallet linking is not enabled by the site administrator.');
  }catch(e){if(epoch===generation)setStatus(`Wallet status unavailable (${e.message})`,true);}
}

// Deliberately NOT called until the user presses Connect. No wallet SDK imports,
// provider inspection, provider event listeners, eager connect, or injected
// window.solana access during normal page load.
function availableWalletsOnUserClick() {
  const candidates=[
    {label:'Phantom',provider:window.phantom?.solana},
    {label:'Solflare',provider:window.solflare},
  ].filter(w=>w.provider && typeof w.provider.connect==='function' &&
             typeof w.provider.signMessage==='function');
  if(!candidates.length && window.solana && typeof window.solana.connect==='function' &&
     typeof window.solana.signMessage==='function'){
    candidates.push({label:'Solana wallet',provider:window.solana});
  }
  return candidates;
}

async function runWallet(provider) {
  if(busy||!signedIn())return;
  busy=true;connectButton.disabled=true;
  if(modal?.open)modal.close();
  try {
    setStatus('Waiting for wallet connection approval…');
    const connected=await provider.connect();
    const walletAddress=String(connected?.publicKey||provider.publicKey||'');
    if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(walletAddress))throw new Error('Wallet did not return a Solana address');
    const challenge=await api('/challenge',{method:'POST',body:JSON.stringify({address:walletAddress})});
    setStatus('Confirm ownership in your wallet by signing a message (not a transaction)…');
    const utf8=new TextEncoder().encode(challenge.message);
    const signed=await provider.signMessage(utf8,'utf8');
    const signature=encodeBase58(signed?.signature||signed);
    const after=String(provider.publicKey||connected?.publicKey||'');
    if(after!==walletAddress)throw new Error('Connected wallet changed during verification');
    await api('/verify',{method:'POST',body:JSON.stringify({challenge_id:challenge.challenge_id,signature})});
    setStatus('Wallet verified and linked. Checking balances…');
    await sync();
  }catch(e){setStatus(e?.message||'Wallet linking cancelled or failed.',true);}
  finally{busy=false;connectButton.disabled=false;}
}

connectButton?.addEventListener('click',()=>{
  if(busy||!signedIn())return;
  // First and only wallet discovery entry point: an explicit user click.
  const wallets=availableWalletsOnUserClick();
  if(!wallets.length){setStatus('No supported browser wallet found. Install Phantom or Solflare, then click Connect.',true);return;}
  if(wallets.length===1){void runWallet(wallets[0].provider);return;}
  choices.replaceChildren();
  for(const wallet of wallets){
    const b=document.createElement('button');b.type='button';
    b.className='account-secondary-button';b.textContent=wallet.label;
    b.addEventListener('click',()=>void runWallet(wallet.provider));choices.append(b);
  }
  modal.showModal();
});
closeModal?.addEventListener('click',()=>modal?.close());
copyButton?.addEventListener('click',async()=>{
  if(!address)return;
  try{await navigator.clipboard.writeText(address);setStatus('Full public wallet address copied.');}
  catch{setStatus('Clipboard unavailable; select and copy the public address.',true);}
});
refreshButton?.addEventListener('click',()=>void loadBalances());
unlinkButton?.addEventListener('click',async()=>{
  if(!address||busy||!signedIn())return;
  if(!confirm('Unlink this wallet from your Gnosis account? This does not disconnect your wallet extension.'))return;
  busy=true;unlinkButton.disabled=true;
  try{await api('/unlink',{method:'POST'});reset();await sync();}
  catch(e){setStatus(e?.message||'Unable to unlink wallet.',true);}
  finally{busy=false;unlinkButton.disabled=false;}
});
let previous=document.body.dataset.gnosisSession;
new MutationObserver(()=>{
  const next=document.body.dataset.gnosisSession;
  if(next===previous)return;
  previous=next;
  if(next==='authenticated')void sync();else reset();
}).observe(document.body,{attributes:true,attributeFilter:['data-gnosis-session']});
window.addEventListener('gnosis:account-session-changed',()=>{
  // No extension inspection or wallet reconnection here. Only a server status read.
  if(signedIn())void sync();else reset();
});
if(signedIn())void sync();
