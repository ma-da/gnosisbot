/**
 * GNOSIS.BOT shared site header, v1.
 * Presentation-only normalization. Moves existing elements rather than cloning them,
 * preserving links, IDs, event targets, accessibility information, and page tools.
 * No API calls, storage, tracking, or reading/consultation behavior.
 */
(function () {
  'use strict';
  const NAV = [
    ['/quantum-oracle.html', 'I Ching'],
    ['/rune-oracle.html', 'Elder Futhark'],
    ['/account.html', 'Account'],
    ['/research.html', 'Research'],
    ['/#contact', 'Contact']
  ];

  function ensureBrand(header) {
    let brand = header.querySelector('.wordmark');
    if (brand) return brand;
    brand = document.createElement('a');
    brand.className = 'wordmark';
    brand.href = '/';
    brand.setAttribute('aria-label', 'gnosis.bot home');
    brand.append('gnosis');
    const dot = document.createElement('span');
    dot.className = 'brand-dot';
    dot.textContent = '.';
    brand.append(dot, 'bot');
    return brand;
  }

  function ensureNav(header) {
    let nav = header.querySelector('.home-nav');
    if (nav) return nav;
    nav = document.createElement('nav');
    nav.className = 'home-nav';
    nav.setAttribute('aria-label', 'Primary navigation');
    for (const [href, name] of NAV) {
      const link = document.createElement('a');
      link.href = href;
      link.textContent = name;
      if (location.pathname === href || (href === '/' && location.pathname === '/')) {
        link.setAttribute('aria-current', 'page');
      }
      nav.append(link);
    }
    return nav;
  }

  function ensureHealth(header) {
    let health = header.querySelector(':scope > .system-health-trigger[data-system-health]');
    if (!health) health = header.querySelector('[data-system-health]');
    if (!health) health = document.querySelector('.gnosis-page-tools [data-system-health]');
    if (!health) {
      health = document.createElement('button');
      health.type = 'button';
      health.className = 'system-health-trigger';
      health.dataset.systemHealth = '';
      health.setAttribute('aria-haspopup', 'dialog');
      health.textContent = 'SYSTEM HEALTH';
    }
    // The shared health handler must see exactly one trigger on the page.
    for (const extra of document.querySelectorAll('[data-system-health]')) {
      if (extra !== health) extra.remove();
    }
    if (!health.classList.contains('system-health-trigger')) health.classList.add('system-health-trigger');
    return health;
  }

  function normalize() {
    const header = document.querySelector('body > header.gnosis-site-header');
    if (!header || header.dataset.gnosisUnifiedHeader === 'v1') return;

    const brand = ensureBrand(header);
    const nav = ensureNav(header);
    const health = ensureHealth(header);
    let group = header.querySelector(':scope > .gnosis-header-main');
    if (!group) {
      group = document.createElement('div');
      group.className = 'gnosis-header-main';
      header.insertBefore(group, header.firstChild);
    }
    group.append(brand, nav);

    let context = group.querySelector('.gnosis-header-context');
    // Preserve miscellaneous header content rather than dropping it.
    for (const child of [...header.children]) {
      if (child === group || child === health) continue;
      if (!context) {
        context = document.createElement('div');
        context.className = 'gnosis-header-context';
        group.append(context);
      }
      context.append(child);
    }

    // Historical I Ching and Rune pages have a secondary header row.
    // Move its controls into the same visual group, left of System Health.
    for (const toolbar of [...document.querySelectorAll('.gnosis-page-tools')]) {
      for (const child of [...toolbar.childNodes]) {
        if (child.nodeType === 3 && !child.textContent.trim()) {
          child.remove();
          continue;
        }
        if (!context) {
          context = document.createElement('div');
          context.className = 'gnosis-header-context';
          group.append(context);
        }
        context.append(child);
      }
      toolbar.remove();
    }
    // A page may have kept only duplicate triggers in the old toolbar.
    if (context && !context.textContent.trim() && !context.querySelector('input,button,a,select')) {
      context.remove();
    }
    header.append(health);
    header.dataset.gnosisUnifiedHeader = 'v1';

    // Policy/auxiliary pages may not load the health component yet.
    // Load it only after the new single trigger is in the document.
    if (![...document.scripts].some(s => (s.getAttribute('src') || '').includes('/assets/js/system-health.js'))) {
      const healthScript = document.createElement('script');
      healthScript.type = 'module';
      healthScript.src = '/assets/js/system-health.js?v=health-v2';
      document.head.append(healthScript);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', normalize, {once:true});
  } else {
    normalize();
  }
})();
