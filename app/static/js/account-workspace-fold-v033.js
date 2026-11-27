/** GNOSIS WORKSPACE COLLAPSE V0.3.3 — static-only, one anchored panel at a time.
 * Existing account/notices/robot/Soul Work scripts retain responsibility for content.
 */
(() => {
  'use strict';
  const root = document.getElementById('gnosis-account-messages');
  if (!root || !root.classList.contains('gnosis-workspace')) return;
  const modules = [...root.querySelectorAll('.gnosis-workspace-module')];
  const buttons = modules.map(m => m.querySelector('.gnosis-workspace-opener'));
  if (modules.length !== 4 || buttons.some(b => !b)) return;
  let active = null;
  let returnFocus = false;

  const close = (restore = false) => {
    if (!active) return;
    const m = active;
    const button = m.querySelector('.gnosis-workspace-opener');
    const panel = m.querySelector('.gnosis-workspace-panel');
    panel.hidden = true;
    button.setAttribute('aria-expanded','false');
    button.setAttribute('aria-label','Open ' + m.querySelector('h4').textContent);
    m.classList.remove('is-open');
    active = null;
    if (restore && document.body.dataset.gnosisSession === 'authenticated') button.focus();
  };
  const open = m => {
    close(false);
    const button = m.querySelector('.gnosis-workspace-opener');
    const panel = m.querySelector('.gnosis-workspace-panel');
    panel.hidden = false;
    button.setAttribute('aria-expanded','true');
    button.setAttribute('aria-label','Close ' + m.querySelector('h4').textContent);
    m.classList.add('is-open');
    active = m;
  };
  for (const m of modules) {
    const button = m.querySelector('.gnosis-workspace-opener');
    const closeButton = m.querySelector('.gnosis-workspace-panel-close');
    button.addEventListener('click', () => active === m ? close(false) : open(m));
    closeButton.addEventListener('click', () => close(true));
  }
  document.addEventListener('pointerdown', event => {
    if (active && !active.contains(event.target)) close(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && active) {event.preventDefault(); close(true);}
  });
  // Remove private DOM exposure and close any flyout on account switch/logout.
  const observer = new MutationObserver(() => {
    if (document.body.dataset.gnosisSession !== 'authenticated' || root.hidden) close(false);
  });
  observer.observe(document.body, {attributes:true,attributeFilter:['data-gnosis-session']});
  observer.observe(root, {attributes:true,attributeFilter:['hidden']});
})();
