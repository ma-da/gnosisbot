/* Gnosis credits V2: client-only claim form and invitation-only signup disclosure.
 * No code is put in URLs, storage, logs, or analytics. No automatic mutation.
 */
const byId = id => document.getElementById(id);

function showMessage(message, error = false) {
  const el = byId('gnosis-claim-message');
  if (!el) return;
  el.textContent = message;
  el.dataset.error = String(error);
}

async function refreshAccountCreditDisplay() {
  // Use the existing authenticated hub contract, never a separate balance cache.
  const r = await fetch('/api/v1/accounts/hub?limit=1&offset=0', {
    credentials: 'same-origin', cache: 'no-store',
  });
  if (!r.ok) return;
  const payload = await r.json();
  const account = payload.account || {};
  const values = {
    'gnosis-hub-available': account.credits,
    'gnosis-hub-reserved': account.reserved,
    'gnosis-hub-total': account.total,
  };
  for (const [id, value] of Object.entries(values)) {
    const el = byId(id);
    if (el && Number.isSafeInteger(value) && value >= 0) el.textContent = String(value);
  }
  const badge = document.querySelector('#session span[title^="Credits currently available"]');
  if (badge && Number.isSafeInteger(account.credits)) badge.textContent = ` (${account.credits})`;
  // Also requests a standard hub refresh, so the existing UI owns its final state.
  window.dispatchEvent(new Event('gnosis:account-session-changed'));
}

const claimForm = byId('gnosis-claim-form');
claimForm?.addEventListener('submit', async event => {
  event.preventDefault();
  const codeEl = byId('gnosis-claim-code');
  const button = byId('gnosis-claim-submit');
  const code = codeEl?.value.trim() || '';
  if (document.body.dataset.gnosisSession !== 'authenticated') {
    showMessage('Please sign in before redeeming a claim code.', true);
    return;
  }
  if (code.length < 32 || code.length > 128) {
    showMessage('Please enter a complete claim code.', true);
    return;
  }
  button.disabled = true;
  showMessage('Redeeming claim code…');
  try {
    const response = await fetch('/api/v1/credits/redeem', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({claim_code: code}),
    });
    if (!response.ok) {
      if (response.status === 401) throw new Error('Session expired. Please sign in again.');
      if (response.status === 400 || response.status === 409 || response.status === 422) {
        throw new Error('Code invalid, expired, or already redeemed.');
      }
      throw new Error(`Unable to redeem code (HTTP ${response.status}).`);
    }
    const result = await response.json();
    if (result.redeemed !== true || !Number.isSafeInteger(result.credits) || result.credits <= 0) {
      throw new Error('Unexpected redemption confirmation. Please refresh your account before retrying.');
    }
    // Clear the sensitive one-time token from the DOM after a confirmed redemption.
    codeEl.value = '';
    showMessage(`Redeemed successfully: ${result.credits} credits added to your account.`);
    try { await refreshAccountCreditDisplay(); }
    catch { /* A failed status refresh must never retry a successful redemption. */ }
  } catch (err) {
    showMessage(err.message || 'Unable to redeem this code.', true);
  } finally {
    button.disabled = false;
  }
});

// This only reveals the preexisting local-key registration form to invitees.
// It does not implement, bypass, or replace any backend registration rules.
const createCard = document.querySelector('#account-auth-view fieldset.account-auth-create');
const inviteInput = byId('invitation');
const authIntro = document.querySelector('#account-auth-view .account-auth-intro');
if (createCard && inviteInput && authIntro && (createCard.hidden || createCard.style.display === 'none')) {
  const reveal = document.createElement('button');
  reveal.type = 'button';
  reveal.className = 'account-secondary-button gnosis-invite-create';
  reveal.textContent = 'Create an account with an invitation';
  authIntro.append(reveal);
  reveal.addEventListener('click', () => {
    createCard.hidden = false;
    createCard.style.removeProperty('display');
    inviteInput.required = true;
    inviteInput.placeholder = 'Required: paste your single-use invitation code';
    reveal.hidden = true;
    inviteInput.focus();
  });
  // The existing activate handler submits to the current registration API.
  // Keep the alpha UI invitation-only even if the older API permits free signup.
  byId('activate')?.addEventListener('click', event => {
    if (!inviteInput.value.trim()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const status = byId('status');
      if (status) {
        status.textContent = 'A valid invitation code is required for alpha registration.';
        status.dataset.error = 'true';
      }
      inviteInput.focus();
    }
  }, true);
}
