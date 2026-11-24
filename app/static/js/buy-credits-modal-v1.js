/* Gnosis Buy Credits modal v1.3 — layout detection repair, presentation only.
 * Keeps the original commerce DOM, event listeners, quote API, and checkout flow.
 * Cross-page deep link: /account.html#buy-credits
 * Account-local event: window.GnosisBuyCredits.open() / data-gnosis-buy-credits
 */
(() => {
  'use strict';
  const MODAL_ID = 'gnosis-buy-credits-dialog';
  const HASH = '#buy-credits';
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  let modal = null;
  let source = null;
  let trigger = null;
  let returnFocus = null;
  let initialized = false;
  let observer = null;

  function isVisible(node) {
    if (!node || !node.isConnected || node.hidden || node.closest('[hidden], [inert]')) return false;
    const style = window.getComputedStyle(node);
    return style.display !== 'none' && style.visibility !== 'hidden';
  }

  function hasCommerceContent(node) {
    if (!node || !node.querySelectorAll) return false;
    // Production has THREE method radios; packages are clickable BUTTONS.
    // V1 incorrectly demanded seven radio inputs, so it never initialized.
    if (node.querySelectorAll('input[type="radio"]').length < 3) return false;
    const text = norm(node.textContent);
    return text.includes('order review') && text.includes('continue to payment') && text.includes('payment method') && text.includes('credit package');
  }

  // Find the *smallest* commerce container; never move the whole account page.
  function findCommerceRoot() {
    const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,[role="heading"]')];
    const heading = headings.find(el => norm(el.textContent) === 'purchase credits');
    if (!heading) return null;
    let node = heading.parentElement;
    while (node && node !== document.body && !['MAIN','HTML'].includes(node.tagName)) {
      if (hasCommerceContent(node)) return { root: node, heading };
      node = node.parentElement;
    }
    return null;
  }

  function findTitle(root, text) {
    return [...root.querySelectorAll('legend,h2,h3,h4,h5,h6,[role="heading"],strong,label,p,span,div')]
      .find(node => norm(node.textContent) === norm(text)) || null;
  }

  // Actual account commerce renders credit packs as card containers, not
  // necessarily <button> elements. Find the FOUR sibling tiles via their
  // server-supplied credit counts, without depending on tag names, class names,
  // or the container's interactive semantics. Do not clone/replace controls.
  const PACK_COUNTS = Object.freeze([1, 11, 16, 31]);
  function packCount(node) {
    if (!node || node.nodeType !== 1) return null;
    // Read text nodes with separators so <strong>1 credits</strong><small>Get
    // a live price</small> is parsed correctly. innerText is empty while the
    // containing <dialog> is closed during initial page initialization.
    const textParts = [];
    const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    for (let item = walk.nextNode(); item; item = walk.nextNode()) {
      textParts.push(item.nodeValue);
    }
    const text = norm(textParts.join(' '));
    const all = [...text.matchAll(/(?:^|\s)(1|11|16|31)\s+credits?\b/g)]
      .map(m => Number(m[1]));
    const unique = [...new Set(all)];
    return unique.length === 1 && /^(?:1|11|16|31)\s+credits?\b/.test(text)
      ? unique[0] : null;
  }

  function packTileSet(node) {
    if (!node) return null;
    // Work from deepest DOM ancestors upwards to find the smallest grid with
    // four distinct sibling cards. Other headings/disclosures are excluded.
    const candidates = [node, ...node.querySelectorAll('*')].reverse();
    for (const holder of candidates) {
      if (holder.closest('#gnosis-buy-credits-dialog .gcm-review')) continue;
      const children = [...holder.children];
      if (children.length < 4) continue;
      const byCount = new Map();
      for (const child of children) {
        const count = packCount(child);
        if (count != null && !byCount.has(count)) byCount.set(count, child);
      }
      if (PACK_COUNTS.every(n => byCount.has(n))) {
        const cards = PACK_COUNTS.map(n => byCount.get(n));
        if (new Set(cards).size === 4) return { holder, cards };
      }
    }
    return null;
  }

  function packCards(node) {
    return packTileSet(node)?.cards || [];
  }

  function findOptionGroup(title, otherTitle, kind) {
    if (!title) return null;
    let node = title.parentElement;
    while (node && node !== source) {
      if (otherTitle && node.contains(otherTitle)) return null;
      if (kind === 'method' && node.querySelectorAll('input[type="radio"]').length === 3)
        return node;
      if (kind === 'pack' && packCards(node).length === 4)
        return node;
      node = node.parentElement;
    }
    return null;
  }

  function tileFor(input, boundary) {
    const label = input.closest('label');
    if (label && boundary.contains(label)) return label;
    let parent = input.parentElement;
    while (parent && parent !== boundary) {
      if (['LABEL','BUTTON'].includes(parent.tagName) || parent.getAttribute('role') === 'radio') return parent;
      if (parent.parentElement && parent.parentElement.querySelectorAll('input[type="radio"]').length > 1) return parent;
      parent = parent.parentElement;
    }
    return null;
  }

  // Preserve all original clickable controls and their attached listeners.
  function arrangeTiles(group, kind, order) {
    const cards = kind === 'method'
      ? [...group.querySelectorAll('input[type="radio"]')].map(input => tileFor(input,group))
      : packCards(group);
    if (cards.length !== (kind === 'method' ? 3 : 4) ||
        cards.some(card => !card) || new Set(cards).size !== cards.length) return false;
    const parents = new Set(cards.map(card => card.parentElement));
    if (parents.size !== 1) return false;
    let holder = cards[0].parentElement;
    if (!holder || holder === document.body) return false;
    const cssClass = kind === 'method' ? 'gcm-method-tiles' : 'gcm-pack-tiles';
    if (holder === group) {
      const options = document.createElement('div');
      cards[0].before(options);
      cards.forEach(card => options.append(card));
      holder = options;
    }
    holder.classList.add(cssClass);
    if (kind === 'method') {
      cards.forEach(card => {
        const t = norm(card.textContent);
        const index = order.findIndex(label => t.includes(label));
        if (index >= 0) card.style.order = String(index + 1);
      });
    }
    return true;
  }

  // Production's commerce stylesheet sets three-across grids. V1.1 could find
  // the modal but did not always identify the option-group ancestors, leaving
  // those grids unchanged. V1.2 uses the already-known control nodes as anchors.
  function nearestContainingGroup(heading, cards, otherHeading, root) {
    for (let node = heading.parentElement; node && node !== root; node = node.parentElement) {
      if (otherHeading && node.contains(otherHeading)) break;
      if (cards.every(card => node.contains(card))) return node;
    }
    return null;
  }

  function tileHolder(group, cards, className, columns) {
    if (!group || cards.length < 1 || cards.some(card => !card)) return false;
    let holder = cards[0].parentElement;
    while (holder && holder !== group && !cards.every(card => holder.contains(card))) {
      holder = holder.parentElement;
    }
    if (!holder) return false;
    if (holder === group) {
      // Do not turn the section heading into a grid item.
      holder = document.createElement('div');
      cards[0].before(holder);
      cards.forEach(card => holder.append(card));
    }
    holder.classList.add(className);
    // Explicit !important inline grid settings win over the legacy account
    // commerce selectors, even when their author CSS uses !important too.
    holder.style.setProperty('display', 'grid', 'important');
    holder.style.setProperty('grid-template-columns', columns, 'important');
    holder.style.setProperty('gap', '10px', 'important');
    holder.style.setProperty('align-items', 'stretch', 'important');
    for (const card of cards) {
      card.style.setProperty('min-width', '0', 'important');
      card.style.setProperty('width', '100%', 'important');
      card.style.setProperty('max-width', 'none', 'important');
      card.style.setProperty('margin', '0', 'important');
    }
    return true;
  }

  const FACE_PRICES = Object.freeze({1:'$3.00', 11:'$10.00',16:'$15.00',31:'$28.00'});
  function paintFixedPrices() {
    if (!source) return;
    for (const card of packCards(source)) {
      const count = packCount(card);
      if (count == null) continue;
      const price = FACE_PRICES[count];
      if (!price) continue;
      let tag = card.querySelector('.gcm-face-price');
      if (!tag) {
        tag = document.createElement('span');
        tag.className = 'gcm-face-price';
        tag.setAttribute('aria-label', 'Package face value ' + price + ' US dollars');
        card.append(tag);
      }
      if (tag.textContent !== price) tag.textContent = price;
      for (const n of card.querySelectorAll('small,span,p,div')) {
        if (n === tag) continue;
        // Keep original quote code and nodes intact, merely suppress the
        // redundant default placeholder text. A later actual quote remains.
        n.classList.toggle('gcm-placeholder-hidden', norm(n.textContent) === 'get a live price');
      }
    }
  }

  function updateResponsiveGrids() {
    if (!source) return;
    const choice = $('.gcm-choice-grid',source);
    if (choice) choice.style.setProperty('grid-template-columns',
      window.innerWidth <= 680 ? 'minmax(0,1fr)' : 'minmax(180px,.92fr) minmax(0,1.48fr)','important');
    const offers = $('.gcm-pack-tiles',source);
    if (offers) offers.style.setProperty('grid-template-columns',
      window.innerWidth <= 370 ? 'minmax(0,1fr)' : 'repeat(2,minmax(0,1fr))','important');
  }

  function arrangeInputs(root) {
    const paymentHeading = findTitle(root, 'Payment method');
    const packHeading = findTitle(root, 'Credit package');
    const methodInputs = [...root.querySelectorAll('input[type="radio"]')];
    const methodCards = methodInputs.map(input => input.closest('label') || input.parentElement);
    const offerCards = packCards(root);
    if (!paymentHeading || !packHeading || methodCards.length !== 3 || offerCards.length !== 4 ||
        methodCards.some(card => !card) || new Set(methodCards).size !== 3) return false;

    const payments = nearestContainingGroup(paymentHeading, methodCards, packHeading, root);
    const packs = nearestContainingGroup(packHeading, offerCards, paymentHeading, root);
    if (!payments || !packs || payments === packs || payments.contains(packs) || packs.contains(payments)) return false;

    // Scope our layout to the two purchasing sections only, not legal notices.
    payments.classList.add('gcm-method-group');
    packs.classList.add('gcm-pack-group');
    let layout = $('.gcm-choice-grid', root);
    if (!layout) {
      layout = document.createElement('div');
      layout.className = 'gcm-choice-grid';
      payments.before(layout);
    }
    layout.append(payments, packs);
    layout.style.setProperty('display','grid','important');
    layout.style.setProperty('grid-template-columns','minmax(180px,.92fr) minmax(0,1.48fr)','important');
    layout.style.setProperty('gap','16px','important');
    layout.style.setProperty('min-width','0','important');

    if (!tileHolder(payments,methodCards,'gcm-method-tiles','minmax(0,1fr)') ||
        !tileHolder(packs,offerCards,'gcm-pack-tiles','repeat(2,minmax(0,1fr))')) return false;

    // DOM order as well as visual order for logical keyboard navigation.
    const ordered = ['stripe','rstory','solana'].map(key => methodCards.find(card => norm(card.textContent).includes(key)));
    if (ordered.every(Boolean) && ordered.every(card => card.parentElement === ordered[0].parentElement)) {
      ordered.forEach(card => card.parentElement.append(card));
    }
    paintFixedPrices();
    updateResponsiveGrids();
    root.classList.add('gcm-layout-ready');
    return true;
  }

  function arrangeReview(root) {
    const title = findTitle(root, 'Order review');
    if (!title) return false;
    let review = title.parentElement;
    while (review && review !== root) {
      const text = norm(review.textContent);
      if (text.includes('receive') && text.includes('continue to payment') && text.includes('order review')) break;
      review = review.parentElement;
    }
    if (!review || review === root) return false;
    review.classList.add('gcm-review');
    const choices = $('.gcm-choice-grid', root);
    if (choices) {
      let common = choices.parentElement;
      while (common && common !== root && !common.contains(review)) common = common.parentElement;
      if (common && common !== root) common.classList.add('gcm-main-layout');
    }
    // The dynamic quote text may be in an <output>, <p> or plain text child.
    // Mark the smallest text-owning element instead of guessing a heading tag.
    const walker = document.createTreeWalker(review, NodeFilter.SHOW_TEXT);
    for (let textNode = walker.nextNode(); textNode; textNode = walker.nextNode()) {
      const v = norm(textNode.textContent);
      if (v.startsWith('staging only') || v.startsWith('illustrative:')) {
        const owner = textNode.parentElement;
        if (owner && owner !== review && norm(owner.textContent).length < 250) {
          owner.classList.add('gcm-review-total');
        }
      }
    }
    for (const node of review.querySelectorAll('dt,dd')) node.classList.add('gcm-detail-cell');
    return true;
  }

  function authenticated() {
    // The commerce panel is permitted to render to admins only in staging.
    // Do not reveal it outside the account hub's normal session visibility.
    const hub = $('#gnosis-hub-panel');
    if (hub && !isVisible(hub)) return false;
    if (!isVisible(modal?.parentElement)) return false;
    const accountCopy = $('#copy-account-id');
    if (accountCopy && !isVisible(accountCopy)) return false;
    return true;
  }

  function syncTrigger() {
    if (!initialized) return;
    const allowed = authenticated();
    if (trigger.hidden !== !allowed) trigger.hidden = !allowed;
    if (!allowed && modal.open) modal.close();
    if (allowed && (location.hash === HASH || new URLSearchParams(location.search).get('buy') === 'credits')) open();
  }

  function open() {
    if (!initialized || !authenticated()) return false;
    if (!modal.open) {
      reconcileLayout();
      returnFocus = document.activeElement;
      modal.showModal();
      $('.gcm-close', modal)?.focus();
    }
    return true;
  }

  function close() {
    if (modal?.open) modal.close();
  }

  function reconcileLayout() {
    if (!source) return;
    // Account commerce builds its pack tiles asynchronously. V1.2 only
    // attempted this during initial page load, then remained 'unmatched'.
    if (source.dataset.gcmChoices !== 'ready' ||
        !$('.gcm-choice-grid .gcm-pack-tiles', source)) {
      source.dataset.gcmChoices = arrangeInputs(source) ? 'ready' : 'unmatched';
    }
    if (source.dataset.gcmReview !== 'ready') {
      source.dataset.gcmReview = arrangeReview(source) ? 'ready' : 'unmatched';
    }
    paintFixedPrices();
  }

  function install() {
    if (initialized) return true;
    const found = findCommerceRoot();
    const copyButton = $('#copy-account-id');
    if (!found || !copyButton) return false;
    const { root, heading } = found;
    if (root === copyButton.parentElement || root.contains(copyButton)) return false;
    source = root;

    modal = document.createElement('dialog');
    modal.id = MODAL_ID;
    modal.className = 'gcm-dialog';
    modal.setAttribute('aria-modal','true');
    if (!heading.id) heading.id = 'gcm-heading';
    modal.setAttribute('aria-labelledby',heading.id);
    const toolbar = document.createElement('div');
    toolbar.className = 'gcm-toolbar';
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'gcm-close';
    dismiss.textContent = 'Close ×';
    dismiss.setAttribute('aria-label','Close purchase credits');
    dismiss.addEventListener('click',close);
    toolbar.append(dismiss);
    // Insert dialog where original commerce lived to preserve any signed-in parent gating.
    root.before(modal);
    modal.append(toolbar, root);
    root.classList.add('gcm-content-root');

    const choicesReady = arrangeInputs(root);
    const reviewReady = arrangeReview(root);
    root.dataset.gcmChoices = choicesReady ? 'ready' : 'unmatched';
    root.dataset.gcmReview = reviewReady ? 'ready' : 'unmatched';

    trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.id = 'gnosis-buy-credits-button';
    trigger.className = 'account-quiet-button gcm-buy-trigger';
    trigger.textContent = 'Buy Credits';
    trigger.hidden = true;
    trigger.setAttribute('aria-haspopup','dialog');
    trigger.setAttribute('aria-controls',MODAL_ID);
    trigger.addEventListener('click', open);
    copyButton.before(trigger);

    modal.addEventListener('close', () => {
      if (returnFocus && returnFocus.isConnected && typeof returnFocus.focus === 'function') returnFocus.focus();
      returnFocus = null;
      // Remove the deep link so subsequent ordinary navigation doesn't reopen it.
      if (location.hash === HASH) history.replaceState(null, '', location.pathname + location.search);
    });
    modal.addEventListener('click', event => { if (event.target === modal) close(); });
    initialized = true;
    syncTrigger();
    return true;
  }

  function handleDeepLink(event) {
    const link = event.target.closest?.('a[href], [data-gnosis-buy-credits]');
    if (!link) return;
    if (link.hasAttribute('data-gnosis-buy-credits')) {
      if (open()) event.preventDefault();
      return;
    }
    if (!(link instanceof HTMLAnchorElement)) return;
    const target = new URL(link.href, location.href);
    if (target.origin === location.origin && target.pathname === location.pathname && target.hash === HASH) {
      if (open()) event.preventDefault();
    }
  }

  // Debug status contains no account data, payment details or credentials.
  function status() {
    return Object.freeze({
      initialized,
      foundCommerce: !!findCommerceRoot(),
      methodRadios: document.querySelectorAll('input[type="radio"]').length,
      packageButtons: source ? packCards(source).length : 0,
      modalCreated: !!modal,
      triggerCreated: !!trigger,
      choiceLayout: source?.dataset.gcmChoices || 'absent',
      reviewLayout: source?.dataset.gcmReview || 'absent',
    });
  }
  window.GnosisBuyCredits = Object.freeze({ open, close, status });
  document.addEventListener('click',handleDeepLink);
  window.addEventListener('hashchange',() => { if (location.hash === HASH) open(); });
  window.addEventListener('resize', updateResponsiveGrids, {passive:true});
  function boot() {
    install();
    // Watch for auth changes and pages where the commerce panel arrives after fetching.
    observer = new MutationObserver(() => {
      if (!initialized) install();
      if (initialized) { syncTrigger(); reconcileLayout(); }
    });
    observer.observe(document.body, {subtree:true,childList:true,attributes:true,attributeFilter:['hidden','inert','data-gnosis-session']});
    if (initialized) syncTrigger();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();
