/** GNOSIS account layout v0.3: read-only account identity + key security dialog.
 * Wallet registration is deliberately unimplemented until signed-proof API exists. */
const byId = (id) => document.getElementById(id);
const identity = byId('gnosis-account-id-display');
const securityDialog = byId('gnosis-security-notice');
const securityOpen = byId('gnosis-security-notice-trigger');
const securityClose = byId('gnosis-security-notice-close');
let requestEpoch = 0;
const isAuthenticated = () => document.body.dataset.gnosisSession === 'authenticated';

async function syncIdentity() {
  const token = ++requestEpoch;
  if (!identity) return;
  if (!isAuthenticated()) {
    identity.textContent = '—';
    if (securityDialog?.open) securityDialog.close();
    if (byId('gnosis-account-solana-wallet')) byId('gnosis-account-solana-wallet').value = '';
    return;
  }
  identity.textContent = 'Checking account…';
  try {
    const response = await fetch('/api/v1/accounts/me', {credentials:'same-origin',cache:'no-store'});
    if (!response.ok) throw new Error('Account information unavailable');
    const data = await response.json();
    if (token !== requestEpoch || !isAuthenticated()) return;
    const value = typeof data?.account_id === 'string' ? data.account_id : '';
    identity.textContent = /^[A-Za-z0-9_.:-]{12,180}$/.test(value) ? value : 'Account ID unavailable';
  } catch {
    if (token === requestEpoch && isAuthenticated()) identity.textContent = 'Account ID unavailable';
  }
}

securityOpen?.addEventListener('click', () => {
  if (!isAuthenticated() || !securityDialog) return;
  securityDialog.showModal();
});
securityClose?.addEventListener('click', () => securityDialog?.close());
securityDialog?.addEventListener('click', (e) => {if (e.target === securityDialog) securityDialog.close();});
securityDialog?.addEventListener('close', () => {if (isAuthenticated()) securityOpen?.focus();});
let prior = document.body.dataset.gnosisSession;
new MutationObserver(() => {
  const next = document.body.dataset.gnosisSession;
  if (next === prior) return;
  prior = next;
  void syncIdentity();
}).observe(document.body, {attributes:true,attributeFilter:['data-gnosis-session']});
window.addEventListener('gnosis:account-session-changed', () => {
  // Clear any prior account's public identifier before a new hub authentication.
  ++requestEpoch;
  if (identity) identity.textContent = '—';
  if (securityDialog?.open) securityDialog.close();
});
void syncIdentity();
