/** Live account-session indicator. Public keys never transmitted by this widget. */
import { getAccount } from './account-auth.js?v=1';
const header = document.querySelector('header');
if (header && !document.getElementById('gnosis-oracle-account-status')) {
  const link = document.createElement('a');
  link.id = 'gnosis-oracle-account-status';
  link.href = '/account.html';
  link.textContent = 'Account';
  link.setAttribute('aria-label', 'Account status');
  link.style.cssText = 'display:inline-flex;align-items:center;gap:.4rem;font-size:.82rem;white-space:nowrap;opacity:.86';
  header.append(link);
  async function refresh() {
    try {
      const account = await getAccount();
      link.textContent = account
        ? `Signed in · ${account.credits} available credits`
        : 'Sign in / Account';
      link.dataset.authenticated = account ? 'true' : 'false';
    } catch {
      link.textContent = 'Account · status unavailable';
      link.dataset.authenticated = 'unknown';
    }
  }
  void refresh();
  window.addEventListener('focus', () => { void refresh(); });
  window.addEventListener('gnosis:account-session-changed', () => { void refresh(); });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void refresh();
  });
}
