/* Gnosis.bot legal policies — shared modal presentation, one canonical HTML source.
 * No tracking, submission, or consent state changes. Links work normally without JS.
 */
(() => {
  'use strict';
  const paths = new Map([
    ['/terms.html', 'Terms of Use'],
    ['/privacy.html', 'Privacy Policy'],
    ['/ai-policy.html', 'AI Policy'],
  ]);
  const create = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };

  function initialize() {
    if (document.getElementById('gnosis-legal-dialog')) return;
    const dialog = create('dialog', 'gnosis-legal-dialog');
    dialog.id = 'gnosis-legal-dialog';
    dialog.setAttribute('aria-label', 'Site policy');

    const toolbar = create('div', 'gnosis-legal-modal-toolbar');
    const descriptor = create('span', 'gnosis-legal-modal-label', 'GNOSIS.BOT / SITE POLICIES');
    const actions = create('div', 'gnosis-legal-modal-actions');
    const full = create('a', 'gnosis-legal-full-link', 'Open full page');
    full.href = '/terms.html';
    // Opening a full page is a deliberate navigation, not another modal.
    full.dataset.legalFullPage = 'true';
    const close = create('button', 'gnosis-legal-modal-close', 'Close ×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close policy');
    actions.append(full, close);
    toolbar.append(descriptor, actions);
    const content = create('div', 'gnosis-legal-modal-content');
    content.id = 'gnosis-legal-modal-content';
    dialog.append(toolbar, content);
    document.body.append(dialog);

    let requested = 0;
    let returnFocus = null;
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener('close', () => {
      requested++;
      if (returnFocus && returnFocus.isConnected) returnFocus.focus({preventScroll:true});
      returnFocus = null;
    });

    async function showPolicy(path, trigger) {
      const first = !dialog.open;
      if (first) {
        returnFocus = trigger;
        dialog.showModal();
        close.focus({preventScroll:true});
      }
      const sequence = ++requested;
      const pageName = paths.get(path);
      full.href = path;
      content.replaceChildren(create('p', 'gnosis-legal-modal-loading', `Loading ${pageName}…`));
      dialog.removeAttribute('aria-labelledby');
      dialog.setAttribute('aria-label', pageName);
      try {
        const response = await fetch(path, {credentials:'same-origin', cache:'no-store'});
        if (!response.ok) throw new Error('Policy page unavailable');
        const html = new DOMParser().parseFromString(await response.text(), 'text/html');
        const article = html.querySelector('article.legal-document');
        if (!article || !article.querySelector('h1')) throw new Error('Policy document not found');
        if (sequence !== requested || !dialog.open) return;
        const copied = document.importNode(article, true);
        copied.querySelector('h1').id = 'gnosis-legal-modal-title';
        content.replaceChildren(copied);
        dialog.setAttribute('aria-labelledby','gnosis-legal-modal-title');
        dialog.removeAttribute('aria-label');
        content.scrollTop = 0;
      } catch (error) {
        if (sequence !== requested || !dialog.open) return;
        const p = create('p', '', `Couldn't load ${pageName} here. You can open its full page instead.`);
        const a = create('a', '', `Open ${pageName}`);
        a.href = path;
        a.dataset.legalFullPage = 'true';
        content.replaceChildren(p, a);
      }
    }

    document.addEventListener('click', event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (!(event.target instanceof Element)) return;
      const link = event.target.closest('a[href]');
      if (!link || link.dataset.legalFullPage === 'true' || link.target && link.target !== '_self' || link.hasAttribute('download')) return;
      let url;
      try { url = new URL(link.href, location.href); } catch { return; }
      if (url.origin !== location.origin || !paths.has(url.pathname)) return;
      event.preventDefault();
      void showPolicy(url.pathname, link);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once:true});
  else initialize();
})();
