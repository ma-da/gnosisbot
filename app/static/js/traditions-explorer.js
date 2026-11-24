/**
 * Gnosis.bot dual-tradition I Ching interpretation explorer.
 * Presentation-only: consumes already assigned corpus records, never generates
 * a cast, requests a service, changes provenance, or writes a receipt.
 */
const TRADITIONS = Object.freeze({
  taoist: { name: 'Taoist', scholar: 'Liu Yiming' },
  confucian: { name: 'Confucian', scholar: 'Cheng Yi' }
});
const ALL_POSITIONS = [1, 2, 3, 4, 5, 6];
let root = null;
let activeView = 'compare';
let browseAllLines = false;
let activeContext = null;

function element(tag, className = '', content = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content != null) node.textContent = String(content);
  return node;
}
function appendText(parent, heading, value, {tag = 'p', className = ''} = {}) {
  if (typeof value !== 'string' || !value.trim()) return;
  const block = element('div', `gte-field ${className}`.trim());
  block.append(element('h4', 'gte-field-label', heading), element(tag, 'gte-field-copy', value));
  parent.append(block);
}
function note(value, className = '') {
  return element('p', `gte-note ${className}`.trim(), value);
}
function details(label, className = '') {
  const d = element('details', `gte-details ${className}`.trim());
  d.append(element('summary', '', label));
  return d;
}
function sourceLink(source) {
  if (!source || typeof source !== 'object') return null;
  const original = source.original_chinese || {};
  const href = original.revision_url || original.url;
  if (typeof href !== 'string') return null;
  try {
    const u = new URL(href);
    if (u.protocol !== 'https:' || u.hostname !== 'zh.wikisource.org') return null;
    const link = element('a', 'gte-source-link', 'View source text');
    link.href = u.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  } catch { return null; }
}
function createShell() {
  if (root) return root;
  const originalSection = document.querySelector('#reading-sections');
  if (!originalSection?.parentElement) return null;
  root = element('section', 'gnosis-traditions-explorer');
  root.id = 'gnosis-traditions-explorer';
  root.hidden = true;
  root.setAttribute('aria-labelledby', 'gte-heading');
  // Crucially: this is *after* the existing Now/Becoming instrument and the
  // original interpretation/provenance section. No existing UI is replaced.
  originalSection.insertAdjacentElement('afterend', root);
  root.addEventListener('click', event => {
    const control = event.target.closest('button[data-gte-view], button[data-gte-lines]');
    if (!control || !root.contains(control)) return;
    const view = control.dataset.gteView;
    const lines = Boolean(control.dataset.gteLines);
    if (view) activeView = view;
    else if (lines) browseAllLines = !browseAllLines;
    if (activeContext) {
      paint();
      // Re-rendered button must reclaim keyboard focus after a choice.
      const replacement = view
        ? root.querySelector(`button[data-gte-view="${view}"]`)
        : root.querySelector('button[data-gte-lines]');
      replacement?.focus({preventScroll: true});
    }
  });
  return root;
}
function createHeader(record) {
  const header = element('header', 'gte-header');
  const top = element('div', 'gte-heading-copy');
  top.append(element('p', 'gte-eyebrow', 'INTERPRETATION / TRADITIONS'));
  const h2 = element('h2', '', 'The Book of Changes — Two Perspectives');
  h2.id = 'gte-heading';
  top.append(h2, note(`Hexagram ${String(record.number).padStart(2, '0')} · ${record.name || record.title || 'Interpretations'} · ${record.chinese || ''} ${record.pinyin || ''}`));
  const phase = element('span', 'gte-phase-label', activeContext.phase === 'now' ? 'NOW · PRIMARY' : 'BECOMING · RELATING');
  header.append(top, phase);
  return header;
}
function createControls() {
  const bar = element('div', 'gte-toolbar');
  const group = element('div', 'gte-choice-group');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', 'Interpretive tradition');
  for (const [view, label] of [['taoist', 'Taoist'], ['confucian', 'Confucian'], ['compare', 'Compare both']]) {
    const button = element('button', 'gte-tab', label);
    button.type = 'button';
    button.dataset.gteView = view;
    button.setAttribute('aria-pressed', String(activeView === view));
    group.append(button);
  }
  bar.append(group, note('The concise interpretation above uses the Taoist default. This section shows the complete separate traditions.'));
  return bar;
}
function createClassical(record) {
  const c = record.classical || {};
  const panel = details('Classical Zhouyi · Judgment, Great Image, and original Chinese', 'gte-classical');
  const inside = element('div', 'gte-details-body');
  appendText(inside, 'Judgment · English translation', c.judgment_en);
  appendText(inside, 'Great Image · English translation', c.image_en);
  const originals = details('View original Chinese');
  const chinese = element('div', 'gte-details-body gte-originals');
  appendText(chinese, 'Judgment · 原文', c.judgment_zh);
  appendText(chinese, 'Great Image · 原文', c.image_zh);
  if (chinese.childElementCount) { originals.append(chinese); inside.append(originals); }
  if (c.historical_note) {
    const scope = details('Translation scope and historical note');
    const wrap = element('div', 'gte-details-body');
    wrap.append(note(c.historical_note));
    scope.append(wrap);
    inside.append(scope);
  }
  panel.append(inside);
  return panel;
}
function traditionCard(record, name) {
  const item = record[name];
  if (!item || typeof item !== 'object') return note(`The ${name} tradition is unavailable for this hexagram.`, 'gte-warning');
  const meta = TRADITIONS[name];
  const card = element('article', `gte-card gte-card--${name}`);
  card.append(element('p', 'gte-card-tradition', `${meta.name.toUpperCase()} · ${meta.scholar}`));
  card.append(element('h3', 'gte-card-title', item.title || record.title || meta.name));
  appendText(card, 'Essence', item.essence, {className:'gte-essence'});
  appendText(card, 'Modern interpretation', item.modern_meaning);
  const expanded = details('Archetype, historical commentary, guidance & reflection');
  const content = element('div', 'gte-details-body');
  appendText(content, 'Archetypal meaning', item.archetypal_meaning);
  appendText(content, 'Historical foundation', item.historical_core);
  appendText(content, 'Advice', item.advice);
  appendText(content, 'Pitfall / shadow', item.shadow);
  appendText(content, 'Reflection question', item.reflection_question);
  if (Array.isArray(item.themes) && item.themes.length) appendText(content, 'Themes', item.themes.join(' · '));
  expanded.append(content);
  card.append(expanded);
  const evidence = details('Original commentary evidence and source');
  const ebody = element('div', 'gte-details-body');
  appendText(ebody, 'Chinese source excerpt', item.evidence_zh);
  if (item.sources) {
    ebody.append(note([item.sources.author, item.sources.work].filter(Boolean).join(' · ')));
    const link = sourceLink(item.sources);
    if (link) ebody.append(link);
  }
  evidence.append(ebody);
  card.append(evidence);
  return card;
}
function visibleTraditions() {
  return activeView === 'compare' ? ['taoist', 'confucian'] : [activeView];
}
function createTraditions(record) {
  const grid = element('div', 'gte-traditions-grid');
  grid.dataset.columns = String(visibleTraditions().length);
  for (const name of visibleTraditions()) grid.append(traditionCard(record, name));
  return grid;
}
function linePanel(record, position) {
  const classical = record.classical?.lines?.[position - 1];
  const box = element('article', 'gte-line');
  box.append(element('h4', 'gte-line-heading', `Line ${position} · ${classical?.label_zh || 'from the bottom'}`));
  if (classical) {
    appendText(box, 'Classical line · English', classical.translation_en);
    const original = details('Original line text');
    original.append(element('p', 'gte-chinese', classical.text_zh || ''));
    box.append(original);
  }
  const grid = element('div', 'gte-line-grid');
  grid.dataset.columns = String(visibleTraditions().length);
  for (const name of visibleTraditions()) {
    const item = record[name]?.lines?.[position - 1];
    if (!item) continue;
    const pane = element('div', 'gte-line-commentary');
    pane.append(element('h5', '', `${TRADITIONS[name].name} · ${TRADITIONS[name].scholar}`));
    appendText(pane, 'Interpretation', item.interpretation);
    appendText(pane, 'Reflection', item.reflection);
    if (item.evidence_zh) {
      const original = details('Original commentary excerpt');
      original.append(element('p', 'gte-chinese', item.evidence_zh));
      pane.append(original);
    }
    grid.append(pane);
  }
  box.append(grid);
  return box;
}
function specialPanel(record, movingCount, phase) {
  const passage = record.classical?.special;
  if (!passage) return null;
  const applicable = phase === 'now' && movingCount === 6;
  const block = details(`Special passage · ${passage.label_zh || 'all six changing'}${applicable ? ' · applicable to this cast' : ' · reference'}`);
  if (applicable) block.open = true;
  const content = element('div', 'gte-details-body');
  content.append(note(applicable
    ? 'All six lines of Now are changing; this special use-nine/use-six passage is relevant.'
    : 'Reference passage. Traditionally considered when all six lines of this hexagram are changing in the primary reading.'));
  appendText(content, 'Classical source · English', passage.translation_en);
  appendText(content, 'Classical source · Chinese', passage.text_zh);
  const grid = element('div', 'gte-line-grid');
  grid.dataset.columns = String(visibleTraditions().length);
  for (const name of visibleTraditions()) {
    const item = record[name]?.special;
    if (!item) continue;
    const pane = element('div', 'gte-line-commentary');
    pane.append(element('h5', '', `${TRADITIONS[name].name} special passage`));
    appendText(pane, 'Interpretation', item.interpretation);
    appendText(pane, 'Reflection', item.reflection);
    if (item.evidence_zh) {
      const original = details('Original commentary excerpt');
      original.append(element('p', 'gte-chinese', item.evidence_zh));
      pane.append(original);
    }
    grid.append(pane);
  }
  content.append(grid);
  block.append(content);
  return block;
}
function createLines(record, reading, phase) {
  const section = element('section', 'gte-lines');
  const row = element('div', 'gte-lines-heading');
  row.append(element('h3', '', 'Changing lines & their commentaries'));
  const button = element('button', 'gte-lines-button', browseAllLines ? 'Show only changing lines' : 'Browse all six reference lines');
  button.type = 'button';
  button.dataset.gteLines = 'toggle';
  button.setAttribute('aria-pressed', String(browseAllLines));
  row.append(button);
  section.append(row);
  const moving = Array.isArray(reading?.moving_positions_bottom_to_top)
    ? reading.moving_positions_bottom_to_top.filter(p => Number.isInteger(p) && p >= 1 && p <= 6)
    : [];
  const positions = browseAllLines ? ALL_POSITIONS : (phase === 'now' ? moving : []);
  if (phase !== 'now') section.append(note('Changing-line commentary belongs to the Now hexagram. On Becoming, use “Browse all six reference lines” to study the relating hexagram’s lines.'));
  else if (!moving.length) section.append(note('No lines change in this reading. Browse all six lines to review the reference text.'));
  else section.append(note(`Now has ${moving.length} changing line${moving.length === 1 ? '' : 's'}; positions are numbered bottom (1) to top (6).`));
  if (positions.length) {
    const items = element('div', 'gte-line-list');
    for (const position of positions) items.append(linePanel(record, position));
    section.append(items);
  }
  const special = specialPanel(record, moving.length, phase);
  if (special) section.append(special);
  return section;
}
function paint() {
  const shell = createShell();
  if (!shell || !activeContext) return;
  const {record, reading, phase} = activeContext;
  shell.replaceChildren();
  if (!record || typeof record !== 'object' || !record.taoist || !record.confucian || !record.classical) {
    shell.hidden = false;
    shell.append(note('Full interpretive records are not available for this reading; the original interpretation above remains unchanged.', 'gte-warning'));
    return;
  }
  shell.append(createHeader(record), createControls(), createClassical(record), createTraditions(record), createLines(record, reading, phase));
  const footer = element('footer', 'gte-footer');
  footer.append(note(`Gnosis Edition · corpus ${record.corpus_version || 'version unavailable'} · ${record.editorial_status || 'Editorial status unavailable'}. Historical source material, AI-assisted translations and contemporary synthesis are distinct from the measured casting.`));
  shell.append(footer);
  shell.hidden = false;
}
/** Called ONLY from app.js's existing, post-reveal render path. */
export function renderTraditionExplorer({interpretation, reading, phase}) {
  if (!['now', 'becoming'].includes(phase)) return;
  activeContext = {record: interpretation, reading, phase};
  paint();
}
