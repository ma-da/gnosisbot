/** Gnosis Workspace v0.2. UI prototype: never claims, awards or submits paid work. */
const $ = (id) => document.getElementById(id);
const workspace = $('gnosis-account-messages');
const robots = $('gnosis-robot-list');
const isAuthenticated = () => document.body.dataset.gnosisSession === 'authenticated';
let epoch = 0;

const buttons = [...document.querySelectorAll('[data-workspace-view]')];
function chooseView(value) {
  for (const button of buttons) {
    button.setAttribute('aria-pressed', String(button.dataset.workspaceView === value));
  }
  for (const panel of ['assignments', 'bounties']) {
    const node = $('gnosis-soul-' + panel);
    if (node) node.hidden = panel !== value;
  }
}
buttons.forEach(button => button.addEventListener('click', () => chooseView(button.dataset.workspaceView)));
chooseView('assignments');
const briefToggle = $('gnosis-soul-brief-toggle');
const brief = $('gnosis-soul-brief');
briefToggle?.addEventListener('click', () => {
  if (!brief) return;
  brief.hidden = !brief.hidden;
  briefToggle.setAttribute('aria-expanded', String(!brief.hidden));
  briefToggle.textContent = brief.hidden ? 'View sample brief' : 'Hide sample brief';
});

function note(value) {
  if (!robots) return;
  robots.replaceChildren();
  const p = document.createElement('p');
  p.className = 'gnosis-workspace-status';
  p.textContent = value;
  robots.append(p);
}
function linkForBounty(id) {
  return /^[A-Za-z0-9_-]{3,100}$/.test(id || '')
    ? `https://rentahuman.ai/bounties/${encodeURIComponent(id)}` : null;
}
function renderRobots(data) {
  if (data?.schema !== 'gnosis.workspace-robot-bounties.v1' || !Array.isArray(data.items)) {
    note('Remote listings are unavailable. Browse on RentAHuman for current opportunities.');
    return;
  }
  if (data.status === 'disabled') {
    note('Live listings are not enabled yet. Browse RentAHuman directly.');
    return;
  }
  if (data.status !== 'ok') {
    note('Could not verify current remote listings. Please check the source directly.');
    return;
  }
  if (!data.items.length) {
    note('No recent open remote listings met the current feed criteria.');
    return;
  }
  robots.replaceChildren();
  for (const item of data.items.slice(0, 4)) {
    if (!item || typeof item.title !== 'string' || typeof item.id !== 'string') continue;
    const href = linkForBounty(item.id);
    if (!href) continue;
    const article = document.createElement('article');
    article.className = 'gnosis-robot-item';
    const a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = item.title.slice(0, 140);
    const meta = document.createElement('p');
    meta.textContent = [item.reward_display, item.age_display, 'Open on RentAHuman']
      .filter(v => typeof v === 'string' && v.trim()).join(' · ');
    article.append(a, meta);
    robots.append(article);
  }
  if (!robots.children.length) note('No suitable listings are available.');
}
async function loadRobots(token) {
  note('Checking remote opportunities…');
  try {
    const response = await fetch('/api/v1/accounts/workspace/robot-work', {
      credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}
    });
    if (!response.ok) throw new Error('Unavailable');
    const data = await response.json();
    if (token === epoch && isAuthenticated()) renderRobots(data);
  } catch {
    if (token === epoch && isAuthenticated()) note('Live listings unavailable. Browse RentAHuman directly.');
  }
}
function sync() {
  const token = ++epoch;
  if (!isAuthenticated()) {
    note('Sign in to see external opportunities.');
    if (brief) brief.hidden = true;
    if (briefToggle) {briefToggle.textContent = 'View sample brief';briefToggle.setAttribute('aria-expanded', 'false');}
    chooseView('assignments');
    return;
  }
  void loadRobots(token);
}
let previousSession = document.body.dataset.gnosisSession;
const observer = new MutationObserver(() => {
  const next = document.body.dataset.gnosisSession;
  if (next === previousSession) return;
  previousSession = next;
  sync();
});
observer.observe(document.body, {attributes:true,attributeFilter:['data-gnosis-session']});
window.addEventListener('gnosis:account-session-changed', () => {
  // Never retain data from an earlier authenticated account.
  ++epoch;
  note('Checking account session…');
});
if (workspace) sync();
