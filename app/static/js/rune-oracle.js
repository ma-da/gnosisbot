/* GNOSIS.BOT — Elder Futhark visual alpha 0.2.6
 * M5B authenticated provider / isolated M5A demo provider and authoritative RC1 chronology presentation.
 * Server-assigned readings only; no signing, IBM execution or client-side recognition.
 */
(async () => {
    'use strict';
    const $ = id => document.getElementById(id), txt = (id, v) => { $(id).textContent = v; };
    const NS = 'http://www.w3.org/2000/svg';
    const svg = (tag, attrs = {}) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs))
        n.setAttribute(k, String(v)); return n; };
    const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined)
        n.textContent = text; if (cls)
        n.className = cls; return n; };
    const pct = x => `${(100 * x).toFixed(0)}%`;
    const meanings = window.RUNE_MEANINGS, runeMeanings = new Map(meanings.runes.map(r => [r.name, r]));
    const atlas = new Map(window.RUNE_DEMO_DATA.atlas.map(r => [r.name, r]));
    // An explicit local gallery preserves the designer's extra examples.
    // In server mode, reject invalid/missing data rather than silently substituting samples.
    // 01. Demo source and payload validation
    const query = new URLSearchParams(location.search);
    const localGallery = !query.has('reading') && query.get('gallery') === 'local';
    const demo = !query.has('reading') && (localGallery || query.get('gallery') === 'demo');
    const knownIds = [['pouch', 'pouch'], ['sticks-7', 'sticks'], ['sticks-5000', 'sticks'], ['sticks-5001', 'sticks']];
    const profile = 'dfa681432bcb00a68f390660f1244d90baabb42b2f87648762b360c8923beb1e';
    const assert = (ok) => { if (!ok)
        throw new Error('Invalid or incompatible rune payload.'); };
    function validateFixture(d, mode, server, production = false) {
        assert(d?.mode === mode && ['pouch','sticks'].includes(mode) && d.status === 'ready' && typeof d.reading_id === 'string' && d.reading_id.length > 0);
        if (production) window.GnosisRuneConsultation.checkEnvelope(d, d.reading_id);
        else assert(d.source === 'synthetic_demo' && d.delivery === 'demo');
        if (server)
            assert(d.schema_version === 'rune-reading-v0');
        assert(d.provenance && typeof d.provenance === 'object');
        const validName = n => atlas.has(n) && runeMeanings.has(n);
        if (mode === 'pouch') {
            const a = d.payload?.draws;
            assert(Array.isArray(a) && a.length === 3 && new Set(a.map(x => x.rune_id)).size === 3 && new Set(a.map(x => x.name)).size === 3);
            a.forEach((x, i) => assert(x.position === ['past', 'present', 'future'][i] && Number.isInteger(x.rune_id) && x.rune_id >= 0 && x.rune_id < 24 && validName(x.name)));
        }
        else {
            const c = d.payload?.casting, t = d.payload?.timeline;
            assert(c?.point_count === 256 && c.slots === 72 && Array.isArray(c.chords) && c.chords.length === 72 && t?.casting_size === 72 && t.profile_sha256 === profile && d.provenance.profile_sha256 === profile);
            c.chords.forEach((x, i) => assert(x.sequence === i + 1 && [x.endpoint_a, x.endpoint_b].every(v => Number.isInteger(v) && v >= 0 && v < 256)));
            assert(t.candidates && t.frames && t.first_shown && Array.isArray(t.events));
            for (let i = 0; i <= 72; i++) {
                const f = t.frames[String(i)];
                assert(f && f.shown && Array.isArray(f.compounds));
                for (const [name, x] of Object.entries(f.shown)) {
                    const k = t.candidates[x.primary_id];
                    assert(validName(name) && k && Array.isArray(k.segments) && k.segments.length > 0 && Number.isFinite(x.size) && Number.isFinite(x.quality) && Number.isInteger(x.occurrence_count) && x.occurrence_count >= 1 && Number.isInteger(t.first_shown[name]) && t.first_shown[name] <= i);
                    assert(Array.isArray(x.occurrence_ids) && x.occurrence_ids.length === x.occurrence_count && new Set(x.occurrence_ids).size === x.occurrence_count && x.occurrence_ids.includes(x.primary_id));
                    for (const id of x.occurrence_ids) {
                        const candidate = t.candidates[id];
                        assert(candidate?.rune === name && Array.isArray(candidate.segments) && candidate.segments.length > 0);
                        candidate.segments.forEach(s => assert(Number.isInteger(s.stick) && s.stick >= 1 && s.stick <= i && Number.isFinite(s.t_start) && Number.isFinite(s.t_end) && s.t_start >= 0 && s.t_start < s.t_end && s.t_end <= 1));
                    }
                }
                f.compounds.forEach(x => assert(Array.isArray(x.runes) && x.runes.length >= 2 && x.runes.every(n => Object.hasOwn(f.shown, n))));
            }
        }
        return d;
    }
    async function fetchFixture([id, mode]) {
        const response = await fetch('/api/v1/runes/demo/readings/' + encodeURIComponent(id), { method: 'GET', credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(15000) });
        if (!response.ok)
            throw new Error('Server demonstration unavailable (HTTP ' + response.status + ').');
        return validateFixture(await response.json(), mode, true);
    }
    // Palette preferences are presentation-only; never affect recognition or source data.
    const PALETTE = [
        { id: 'rune-emerge-color', token: '--rune-emerge', key: 'gnosisRuneEmergenceColor', fallback: '#b04a4a', name: 'Selected rune color' },
        { id: 'rune-secondary-color', token: '--rune-secondary', key: 'gnosisRuneSecondaryColor', fallback: '#14818b', name: 'Previous rune color' }
    ];
    function initPalette() {
        // Adapt the existing markup in place, retaining the user's custom page layout.
        const primary = $(PALETTE[0].id);
        const container = el('div', undefined, 'rune-palette');
        container.setAttribute('role', 'group');
        container.setAttribute('aria-label', 'Rune display colors');
        const oldLabel = primary?.closest('label');
        if (oldLabel)
            oldLabel.replaceWith(container);
        else if (primary)
            primary.replaceWith(container);
        else
            (document.querySelector('.rune-provider-actions') || document.querySelector('.rune-provider-bar')).append(container);
        for (const item of PALETTE) {
            const input = $(item.id) || (item.id === PALETTE[0].id && primary) || el('input');
            input.id = item.id;
            input.type = 'color';
            input.className = 'rune-color-swatch';
            input.setAttribute('aria-label', item.name);
            input.title = item.name;
            let value = item.fallback;
            try {
                const saved = localStorage.getItem(item.key);
                if (/^#[0-9a-f]{6}$/i.test(saved || ''))
                    value = saved;
            }
            catch { }
            input.value = value;
            const apply = () => {
                // Set on body, where the rune-page CSS defaults are declared.
                document.body.style.setProperty(item.token, input.value);
                try {
                    localStorage.setItem(item.key, input.value);
                }
                catch { }
            };
            apply();
            input.addEventListener('input', apply);
            container.append(input);
        }
    }
    // 02. Provider initialization and reading state
    let fixtures = [];
    if (demo) {
        try {
            fixtures = localGallery ? window.RUNE_DEMO_DATA.fixtures.map(d => validateFixture(d, d.mode, false)) : await Promise.all(knownIds.map(fetchFixture));
            assert(new Set(fixtures.map(d => d.reading_id)).size === fixtures.length);
        } catch (error) {
            txt('rune-provider-status', 'Demonstration unavailable');
            txt('rune-load-message', error instanceof Error ? error.message : 'Could not load the demonstration.');
            $('rune-load-error').hidden = false;
            return;
        }
    }
    const provider = { list: m => fixtures.filter(f => f.mode === m), get: id => fixtures.find(f => f.reading_id === id) };
    txt('rune-provider-status', demo ? (localGallery ? 'LOCAL GALLERY · seven fixed examples' : 'SERVER DEMO · four fixed M5A examples') : 'Select a method and consult the Oracle');
    const galleryLink = $('rune-gallery-link');
    galleryLink.href = demo ? '/rune-oracle.html' : '/rune-oracle.html?gallery=demo';
    galleryLink.textContent = demo ? 'New reading ↗' : 'Demonstrations ↗';
    if(demo){const alternate=el('a',localGallery?'Server demo ↗':'Local gallery ↗');alternate.href=localGallery?'/rune-oracle.html?gallery=demo':'/rune-oracle.html?gallery=local';galleryLink.after(alternate);}
    document.querySelector('.rune-demo-tag').hidden = !demo;
    document.querySelector('.rune-sample-inline').hidden = !demo;
    $('rune-sample-divider').hidden = !demo;
    $('rune-new-reading').hidden = demo;
    $('rune-source').hidden = !demo;
    const state = { mode: 'sticks', sticks: { id: provider.list('sticks')[0]?.reading_id, step: 0, selected: null }, pouch: { id: provider.list('pouch')[0]?.reading_id, step: 0, selected: null }, timer: null, pendingFocus: [] };
    let consultation = null;
    const cur = () => state[state.mode], reading = () => provider.get(cur().id), maxStep = () => state.mode === 'sticks' ? reading().payload.timeline.casting_size : 3;
    // 03. SVG geometry and shared UI helpers
    const line = (a, b, attrs = {}) => svg('line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1], ...attrs });
    function drawShape(target, lines, opts = {}) {
        target.replaceChildren();
        if (!lines.length)
            return;
        const pts = lines.flat(), xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
        const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
        const d = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1e-9), scale = 144 / d;
        const map = p => [100 + (p[0] - cx) * scale, 100 - (p[1] - cy) * scale];
        for (const [a, b] of lines)
            target.append(line(map(a), map(b), { stroke: opts.color || 'currentColor', 'stroke-width': opts.width || 9, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
    }
    function glyph(name) { const n = svg('svg', { viewBox: '0 0 200 200', 'aria-hidden': 'true' }); drawShape(n, atlas.get(name)?.lines || [], { width: 11 }); return n; }
    function point(i) { const a = 2 * Math.PI * i / 256; return [Math.cos(a), Math.sin(a)]; }
    function map(p) { return [300 + 270 * p[0], 300 - 270 * p[1]]; }
    function interpolation(c, t) { const a = point(c.endpoint_a), b = point(c.endpoint_b); return a.map((v, i) => v + t * (b[i] - v)); }
    function candidateLines(c, bySeq) { return c.segments.map(s => { const ch = bySeq.get(s.stick); return [interpolation(ch, s.t_start), interpolation(ch, s.t_end)]; }); }
    function ring() { const r = $('rune-ring'); r.append(svg('circle', { cx: 300, cy: 300, r: 270, class: 'rune-outline' })); for (let i = 0; i < 256; i++) {
        const p = point(i), major = i % 16 === 0;
        const a = map(p), b = [300 + (major ? 282 : 275) * p[0], 300 - (major ? 282 : 275) * p[1]];
        r.append(line(a, b, { class: `rune-tick${major ? ' major' : ''}` }));
    } for (const [i, x, y] of [[0, 592, 303], [64, 300, 12], [128, 8, 303], [192, 300, 596]]) {
        const t = svg('text', { x, y, class: 'rune-cardinal' });
        t.textContent = i;
        r.append(t);
    } }
    function metric(label, value) { const d = el('div'); d.append(el('span', label), el('strong', value)); return d; }
    function resultButton(name, small, selected, action) { const b = el('button', undefined, 'rune-result'); b.type = 'button'; b.setAttribute('aria-pressed', String(selected)); b.append(glyph(name), el('strong', name), el('small', small)); b.addEventListener('click', action); return b; }
    function choose(name, from) { stop(); cur().selected = name; render(); if (from === 'result')
        [...$('rune-results').children].find(b => b.getAttribute('aria-pressed') === 'true')?.focus(); if (from === 'pouch')
        [...$('rune-pouch-draws').children].find(b => b.getAttribute('aria-pressed') === 'true')?.focus(); }
    // A second, glyph-only view of the same current-frame rune identities.
    // Keep existing buttons when possible so keyboard focus survives each render.
    // This is navigation only: no new reading, recognition, or occurrence counting.
    function renderMeaningSelector(names, selected) {
        const strip = $('rune-meaning-selector');
        if (!strip) return;
        strip.hidden = names.length === 0;
        const existing = new Map([...strip.children].map(b => [b.dataset.rune, b]));
        const wanted = new Set(names);
        for (const [name, button] of existing) {
            if (!wanted.has(name)) button.remove();
        }
        names.forEach((name, index) => {
            let button = existing.get(name);
            if (!button) {
                button = el('button', undefined, 'rune-meaning-glyph');
                button.type = 'button';
                button.dataset.rune = name;
                button.setAttribute('aria-label', `Explore ${name}`);
                button.title = name;
                button.append(glyph(name));
                button.addEventListener('click', () => choose(name, 'meaning'));
            }
            button.setAttribute('aria-pressed', String(name === selected));
            if (strip.children[index] !== button) {
                strip.insertBefore(button, strip.children[index] || null);
            }
        });
    }
    function eventLabel(e) { switch (e.event) {
        case 'emerged': return `${e.rune} emerged`;
        case 'reappeared': return `${e.rune} reappeared`;
        case 'embedded': return `${e.rune} embedded${e.parent_runes?.length ? ' in ' + e.parent_runes.join(' + ') : ''}`;
        case 'count_changed': return `${e.rune}: ${e.previous_count} → ${e.occurrence_count} occurrences`;
        case 'primary_changed': return `${e.rune}: primary highlight updated`;
        default: return `${e.rune}: ${e.event}`;
    } }
    function populateHistory(events) { const h = $('rune-history'); h.replaceChildren(); if (!events.length) {
        h.append(el('p', 'No emergence events at this position.'));
        return;
    } for (const e of events) {
        const row = el('div', undefined, 'rune-history-row'), b = el('button', `#${e.step}`);
        b.type = 'button';
        b.setAttribute('aria-label', `Replay step ${e.step}`);
        b.onclick = () => go(e.step);
        row.append(b, el('span', eventLabel(e)));
        h.append(row);
    } }
    // 04. Interpretation and cosmology
    function grammar(name) { const g = $('rune-grammar'); g.replaceChildren(); const a = atlas.get(name); if (!a) {
        g.append(el('p', 'Select a revealed rune to inspect its geometric definition.'));
        return;
    } g.append(el('p', `${a.support_count} supporting ${a.support_count === 1 ? 'line' : 'lines'} · ${a.composition.join(' + ')}`)); const ul = el('ul'); for (const q of a.qualifiers)
        ul.append(el('li', q)); g.append(ul, el('p', 'Application-specific angular glyph definitions; not a reconstruction of all historical variants.')); }
    function setDetails(name, phase, copy) {
        const r = runeMeanings.get(name), w = meanings.worlds.find(w => w.id === r?.world);
        txt('rune-detail-phase', phase);
        txt('rune-detail-title', name || 'Awaiting a symbol');
        txt('rune-detail-copy', copy);
        grammar(name);
        $('rune-meaning').hidden = !r;
        txt('rune-detail-meta', r ? `${r.traditional_label} · ${w.name} · PATHWAY ${r.pathway}` : '');
        if (!r) {
            for (const id of ['rune-essence', 'rune-archetype', 'rune-interpretation', 'rune-reflection'])
                txt(id, '');
            $('rune-keywords').replaceChildren();
            $('rune-meaning-more').replaceChildren();
            return;
        }
        txt('rune-essence', r.essence);
        txt('rune-archetype', r.archetypal_meaning);
        txt('rune-interpretation', r.interpretation);
        txt('rune-reflection', r.reflection);
        $('rune-keywords').replaceChildren(...r.keywords.map(k => el('span', k)));
        const more = $('rune-meaning-more');
        more.replaceChildren(el('p', 'TRADITIONAL NAME', 'small-lead'), el('p', r.traditional_meaning));
        if (r.historical_note)
            more.append(el('p', r.historical_note));
        more.append(el('p', 'SHADOW', 'small-lead'), el('p', r.shadow), el('p', 'ORIGINAL ASSOCIATIONS', 'small-lead'), el('p', r.source_notes));
        if (r.transcription_note)
            more.append(el('p', r.transcription_note, 'subtle'));
    }
    function renderCosmology(names, complete) {
        const present = new Set(names), total = present.size, counts = Object.fromEntries(meanings.worlds.map(w => [w.id, w.runes.filter(n => present.has(n)).length]));
        txt('rune-world-stage', complete ? 'FINAL READING' : 'CURRENT REPLAY FRAME');
        const worldArea = $('rune-worlds');
        worldArea.replaceChildren();
        for (const w of meanings.worlds) {
            const n = counts[w.id], share = total ? n / total : null, card = el('div', undefined, `rune-world world-${w.id}`);
            card.dataset.world = w.id;
            card.dataset.count = n;
            const head = el('div', undefined, 'rune-world-head');
            head.append(el('strong', w.name), el('span', share === null ? '—' : `${(share * 100).toFixed(1)}%`));
            const track = el('div', undefined, 'rune-world-track'), fill = el('div');
            fill.style.width = `${(share || 0) * 100}%`;
            track.append(fill);
            track.setAttribute('role', 'img');
            track.setAttribute('aria-label', share === null ? 'No share available' : `${w.name}: ${n} of ${total} rune identities`);
            const icons = el('div', undefined, 'rune-world-icons');
            for (const name of w.runes.filter(n => present.has(n))) {
                const b = el('button');
                b.type = 'button';
                b.title = name;
                b.setAttribute('aria-label', `Select ${name}`);
                b.append(glyph(name));
                b.onclick = () => { choose(name); [...$('rune-worlds').querySelectorAll('button')].find(x => x.title === name)?.focus(); };
                icons.append(b);
            }
            if (!n)
                icons.append(el('span', 'None', 'subtle'));
            card.append(head, el('div', w.aett_name, 'rune-world-aett'), track, el('p', `${n} ${n === 1 ? 'identity' : 'identities'}${total ? ' of ' + total : ''}`, 'rune-world-count'), icons, el('p', w.essence, 'rune-world-essence'));
            worldArea.append(card);
        }
        const leaders = total ? meanings.worlds.filter(w => counts[w.id] === Math.max(...Object.values(counts))) : [];
        const summary = $('rune-world-summary');
        summary.replaceChildren();
        if (!total)
            summary.append(el('span', complete ? 'No qualifying identities; no world emphasis.' : 'World emphasis will appear as symbols are revealed.'));
        else {
            summary.append(el('strong', leaders.length === 1 ? `${leaders[0].name} emphasis. ` : `Shared emphasis: ${leaders.map(w => w.name).join(' · ')}. `));
            summary.append(document.createTextNode(leaders.map(w => w.description).join(' ')));
        }
        const matches = meanings.pathways.map(p => ({ p, active: p.runes.filter(n => present.has(n)) })).filter(x => x.active.length >= 2).sort((a, b) => b.active.length - a.active.length || a.p.id - b.p.id);
        const area = $('rune-pathways');
        area.replaceChildren();
        txt('rune-pathway-count', `${matches.filter(x => x.active.length === 3).length} COMPLETE · ${matches.filter(x => x.active.length === 2).length} PARTIAL`);
        for (const { p, active } of matches) {
            const full = active.length === 3, card = el('article', undefined, 'rune-pathway');
            card.dataset.pathway = p.id;
            card.dataset.presence = active.length;
            const head = el('div', undefined, 'rune-pathway-card-head');
            head.append(el('strong', p.title), el('span', full ? '3 / 3 · COMPLETE' : '2 / 3 · PARTIAL', 'mono'));
            card.append(head);
            const strip = el('div', undefined, 'rune-pathway-runes');
            for (const [i, name] of p.runes.entries()) {
                const has = present.has(name), cell = el(has ? 'button' : 'div', undefined, `rune-pathway-member world-${p.verse_world_order[i]}${has ? '' : ' is-absent'}`);
                cell.append(glyph(name), el('span', name), el('small', has ? 'Present' : 'Not present'));
                if (has) {
                    cell.type = 'button';
                    cell.onclick = () => { choose(name); $('rune-pathways').querySelector(`[data-pathway="${p.id}"] button[data-rune="${name}"]`)?.focus(); };
                    cell.dataset.rune = name;
                }
                strip.append(cell);
            }
            card.append(strip);
            if (full) {
                const verse = el('div', undefined, 'rune-pathway-verse');
                verse.append(...p.verse.map(v => el('p', v)));
                card.append(verse, el('p', p.summary, 'rune-pathway-summary'));
            }
            else
                card.append(el('p', `Absent: ${p.runes.filter(n => !present.has(n)).join(', ')}. Full verse appears only when all three are present.`, 'rune-pathway-summary'));
            area.append(card);
        }
        txt('rune-pathway-note', !matches.length ? 'No complete or partial pathway at this stage.' : 'Pathways connect archetypes across worlds; they do not imply shared supporting sticks.');
    }
    // Physical source labels are derived from the verified envelope, never the current selector.
    function sourceLabel(d) {
        if(d.source === 'synthetic_demo') return 'Synthetic demonstration';
        if(d.source === 'classic') return 'Classic · server cryptographic randomness';
        if(d.source === 'qci') return 'QCI · optical quantum randomness';
        if(d.source === 'nist') return 'NIST · public randomness beacon';
        return d.delivery === 'precomputed' ? 'IBM Quantum Past · archived hardware' : 'IBM Quantum Future · live hardware';
    }
    function technology(d) {
        const pouch = d.mode === 'pouch';
        let copy;
        if(d.source === 'synthetic_demo') copy = 'This fixed example is synthetic, not a physical quantum measurement.';
        else if(d.source === 'classic') copy = 'Server cryptographic RNG supplies the bits. No quantum circuit was executed.';
        else if(d.source === 'qci') copy = 'QCI optical quantum noise supplies the random bits; deterministic CPU mapping follows. The IBM rune circuit was not executed.';
        else if(d.source === 'nist') copy = 'A public NIST beacon pulse is expanded deterministically with a versioned, request-bound SHAKE256 derivation. This is not new private entropy; independent signature verification is not established.';
        else copy = pouch ? 'Recorded IBM circuit measurements supply the ordered ranks (15-qubit strict V2A protocol).' : 'Recorded IBM circuit measurements supply the 72 ordered chord slots (18 shots of a 64-qubit circuit).';
        copy += pouch ? ' Three distinct identities are decoded in order from pools of 24, 23 and 22.' : ' The frozen RC1 CPU recognition grammar identifies formations in 72 ordered endpoint pairs.';
        txt('rune-technology-title',sourceLabel(d)); txt('rune-technology-copy',copy);
    }
    function provenance(d) {
        const p = $('rune-provenance'); p.replaceChildren();
        p.append(el('p', `Reading: ${d.reading_id}`), el('p', `Source: ${sourceLabel(d)}`));
        for (const [k,v] of Object.entries(d.provenance || {})) {
            if (v === null || typeof v === 'object') continue;
            p.append(el('p', `${k.replaceAll('_', ' ')}: ${v}`, k.includes('sha256') ? 'rune-hash' : undefined));
        }
        technology(d);
    }
    // Chronology projection. Each frame is authoritative for recognition and counts.
    // Historical overlays are visual memory only: they never feed cosmology, results or counts.
    const timelineCache = new WeakMap();
    // 05. Chronology and persistent formation display
    function indexTimeline(t) {
        if (timelineCache.has(t))
            return timelineCache.get(t);
        const frames = [], seen = new Set();
        let previous = {}, lastSelected = null;
        for (let step = 0; step <= t.casting_size; step++) {
            const shown = t.frames[String(step)].shown;
            const additions = [];
            for (const [name, entry] of Object.entries(shown)) {
                const before = previous[name];
                // A new identity, reappearance, or newly presented occurrence deserves focus.
                if (!before || entry.primary_id !== before.primary_id || entry.occurrence_ids.some(id => !before.occurrence_ids.includes(id)))
                    additions.push(name);
                for (const id of entry.occurrence_ids)
                    seen.add(id);
            }
            // Same-frame events are revealed in deterministic order, without changing the slot count.
            additions.sort((a, b) => shown[a].presentation_rank - shown[b].presentation_rank || a.localeCompare(b));
            if (additions.length)
                lastSelected = additions.at(-1);
            if (!Object.hasOwn(shown, lastSelected)) {
                lastSelected = Object.keys(shown).sort((a, b) => shown[b].primary_step - shown[a].primary_step || a.localeCompare(b))[0] || null;
            }
            frames.push({ additions, seen: [...seen], selected: lastSelected });
            previous = shown;
        }
        timelineCache.set(t, frames);
        return frames;
    }
    // Keep SVG occurrence groups alive across frames to allow real opacity transitions.
    // Remove only geometry that has not yet been encountered at a rewound frame or new sample.
    let overlayReading = null;
    const overlayNodes = new Map();
    function renderFormationMemory(d, frame, selectedId, bySeq) {
        let layer = $('rune-emergence');
        if (!layer) {
            layer = svg('g', { id: 'rune-emergence' });
            $('rune-highlight').before(layer);
        }
        if (overlayReading !== d) {
            layer.replaceChildren();
            overlayNodes.clear();
            overlayReading = d;
        }
        const keep = new Set(frame.seen);
        for (const [id, node] of overlayNodes) {
            if (!keep.has(id)) {
                node.remove();
                overlayNodes.delete(id);
            }
        }
        for (const id of frame.seen) {
            const candidate = d.payload.timeline.candidates[id];
            let group = overlayNodes.get(id);
            if (!group) {
                group = svg('g', { class: 'rune-memory', 'data-candidate': id, 'aria-hidden': 'true' });
                candidateLines(candidate, bySeq).forEach(([a, b], i) => group.append(line(map(a), map(b), { class: 'rune-emerge-line', 'data-stick': candidate.segments[i].stick })));
                layer.append(group);
                overlayNodes.set(id, group);
            }
            // Selected geometry uses primary color; older and nonselected geometry settles at 10%.
            group.classList.toggle('is-selected', id === selectedId);
        }
    }
    // Move the one results rail out of the hidden sticks stage in pouch mode.
    // All existing IDs remain unique; the current frame still controls the displayed identities.
    const resultsRail = $('rune-results').closest('.rune-results-rail');
    function placeResultsRail() {
        if (!resultsRail)
            return;
        if (state.mode === 'sticks')
            $('rune-stick-stage').prepend(resultsRail);
        else
            $('rune-status').after(resultsRail);
        resultsRail.classList.toggle('is-pouch', state.mode === 'pouch');
    }
    // 06. Reading views
    function renderSticks(d) {
        const { casting, timeline: t } = d.payload, s = cur(), step = s.step, f = t.frames[String(step)], shown = f.shown;
        const names = Object.keys(shown).sort((a, b) => (t.first_shown[a] - t.first_shown[b]) || a.localeCompare(b));
        const chronology = indexTimeline(t)[step];
        if (!names.includes(s.selected))
            s.selected = chronology.selected;
        const x = shown[s.selected], candidate = x ? t.candidates[x.primary_id] : null, bySeq = new Map(casting.chords.map(c => [c.sequence, c]));
        const strokes = $('rune-chords');
        const highlight = $('rune-highlight');
        strokes.replaceChildren();
        highlight.replaceChildren();
        let visible = 0;
        for (const c of casting.chords) {
            if (c.sequence > step)
                break;
            if (c.endpoint_a === c.endpoint_b)
                continue;
            visible++;
            strokes.append(line(map(point(c.endpoint_a)), map(point(c.endpoint_b)), { class: 'rune-slot', 'data-stick': c.sequence }));
        }
        $('rune-circle').classList.toggle('has-selection', !!x);
        $('rune-circle').setAttribute('aria-label', `${step} casting slots, ${visible} visible sticks${x ? ', highlighting ' + s.selected : ''}`);
        txt('rune-stick-readout', `${step} / ${t.casting_size} SLOTS`);
        if (candidate) {
            const ls = candidateLines(candidate, bySeq);
            ls.forEach(([a, b], i) => highlight.append(line(map(a), map(b), { class: 'rune-highlight', 'data-stick': candidate.segments[i].stick })));
            drawShape($('rune-isolated'), ls, { color: 'currentColor', width: 7 });
        }
        else
            $('rune-isolated').replaceChildren();
        $('rune-isolated').setAttribute('aria-label', x ? `Isolated ${s.selected} formation` : 'No formation selected');
        txt('rune-focus-name', s.selected || '—');
        txt('rune-focus-sub', x ? `${x.occurrence_count} distinct ${x.occurrence_count === 1 ? 'occurrence' : 'occurrences'} · first shown at ${t.first_shown[s.selected]}` : 'No recognized rune at this step.');
        const m = $('rune-metrics');
        m.replaceChildren();
        if (x)
            m.append(metric('SPAN', pct(x.size)), metric('CONFORMITY', x.quality.toFixed(3)), metric('PRIMARY AT', `#${x.primary_step}`), metric('STICKS', String(new Set(candidate.segments.map(p => p.stick)).size)));
        const components = [...new Set((candidate?.components || []).map(r => r.rune))];
        txt('rune-focus-note', x ? (components.length ? `Contains geometric components: ${components.join(', ')}. Not necessarily independent runes.` : 'Exact recorded-coordinate intervals; no snapping or redrawing.') : 'Advance the casting to reveal possible formations.');
        const results = $('rune-results');
        results.replaceChildren();
        for (const n of names)
            results.append(resultButton(n, `×${shown[n].occurrence_count} · #${t.first_shown[n]}`, n === s.selected, () => choose(n, 'result')));
        if (!names.length)
            results.append(el('p', step === t.casting_size ? 'No qualifying formations in this completed casting.' : 'No qualifying formations yet.', 'rune-empty'));
        renderMeaningSelector(names, s.selected);
        txt('rune-result-label', 'RECOGNIZED SYMBOLS');
        txt('rune-result-count', `${names.length} ${names.length === 1 ? 'IDENTITY' : 'IDENTITIES'} · ${names.reduce((total, n) => total + shown[n].occurrence_count, 0)} OCCURRENCES`);
        const cc = $('rune-compounds');
        cc.replaceChildren();
        cc.hidden = !f.compounds.length;
        if (f.compounds.length) {
            cc.append(el('span', 'COMPOUND GEOMETRY · IDENTITIES RETAINED', 'mono'));
            const pairs = new Map();
            for (const r of f.compounds) {
                const key = r.runes.join(' + ');
                pairs.set(key, r.runes);
            }
            for (const [key, ns] of pairs) {
                const b = el('button', key);
                b.type = 'button';
                b.onclick = () => choose(ns[(ns.indexOf(s.selected) + 1) % ns.length]);
                cc.append(b);
            }
        }
        setDetails(s.selected, 'STICK CASTING', x ? `This ${s.selected} formation is the current primary representative of ${x.occurrence_count} qualifying ${x.occurrence_count === 1 ? 'occurrence' : 'occurrences'}. The highlight follows ${candidate.segments.length} recorded chord intervals.` : step === t.casting_size ? 'The completed casting contains no independently qualifying rune. No recast is required.' : 'The recognition engine has not yet presented a qualifying formation.');
        renderCosmology(names, step === t.casting_size);
        $('rune-history-wrap').hidden = false;
        populateHistory(t.events.filter(e => e.step <= step));
        // Historical geometry is deliberately independent of the current RC1 shown set.
        renderFormationMemory(d, chronology, x?.primary_id, bySeq);
        const ticks = $('rune-event-ticks');
        ticks.replaceChildren();
        for (const k of new Set(t.events.filter(e => e.step <= step).map(e => e.step))) {
            const i = el('i');
            i.style.left = `${k / t.casting_size * 100}%`;
            ticks.append(i);
        }
        txt('rune-method', '');
        $('rune-method').append(el('p', 'The circle uses 256 discrete endpoints. Colored highlights are exact subsegments of the original sticks. Earlier and nonselected formations remain at 10% opacity as visual history, even if no longer independently recognized. Only current-frame identities contribute to the reading. Counts include the primary and distinct other qualifying occurrences, excluding redundant near-duplicates and embedded formations. Different rune identities may share geometry.'));
        txt('rune-status', `${step} of ${t.casting_size} slots · ${visible} visible sticks · ${names.length} recognized ${names.length === 1 ? 'rune' : 'runes'}`);
    }
    function renderPouch(d) {
        renderMeaningSelector([], null); // This navigation strip is sticks-only.
        const s = cur(), draws = d.payload.draws, active = draws.slice(0, s.step);
        if (!active.some(x => x.name === s.selected))
            s.selected = active.at(-1)?.name || null;
        const area = $('rune-pouch-draws');
        area.replaceChildren();
        for (const [i, r] of draws.entries()) {
            const ready = i < s.step, b = el('button', undefined, 'rune-stone');
            b.type = 'button';
            b.disabled = !ready;
            b.setAttribute('aria-pressed', String(ready && r.name === s.selected));
            b.append(el('span', r.position, 'mono'));
            if (ready) {
                b.append(glyph(r.name), el('strong', r.name));
                b.onclick = () => choose(r.name, 'pouch');
            }
            else {
                const question = svg('svg', { viewBox: '0 0 200 200', 'aria-hidden': 'true' });
                question.append(svg('rect', { x: 50, y: 50, width: 100, height: 100, rx: 3, fill: 'none', stroke: '#bcc5c5', 'stroke-width': 2, transform: 'rotate(45 100 100)' }));
                const q = svg('text', { x: 100, y: 110, 'text-anchor': 'middle', 'font-size': 28, fill: '#707779' });
                q.textContent = '?';
                question.append(q);
                b.append(question, el('strong', 'Unrevealed'));
            }
            area.append(b);
        }
        txt('rune-pouch-caption', s.step === 3 ? 'Three distinct identities · draw complete.' : 'Reveal the next rune or replay the ordered draw.');
        const results = $('rune-results');
        results.replaceChildren();
        for (const r of active)
            results.append(resultButton(r.name, r.position.toUpperCase(), r.name === s.selected, () => choose(r.name, 'result')));
        if (!active.length)
            results.append(el('p', 'The three rune identities remain unrevealed.', 'rune-empty'));
        txt('rune-result-label', 'REVEALED SYMBOLS');
        txt('rune-result-count', `${s.step} OF 3`);
        $('rune-compounds').hidden = true;
        $('rune-event-ticks').replaceChildren();
        $('rune-history-wrap').hidden = true;
        renderCosmology(active.map(r => r.name), s.step === 3);
        const x = active.find(r => r.name === s.selected);
        setDetails(s.selected, x ? `POUCH DRAW · ${x.position.toUpperCase()}` : 'POUCH DRAW', x ? `${x.name} is the ${x.position} rune in this ordered draw.` : 'The pouch contains 24 possible rune identities. Reveal each draw in order.');
        $('rune-method').replaceChildren(el('p', 'Past, Present and Future represent three ordered draws. Replay reveals the same assigned result, not a new draw.'));
        txt('rune-status', `${s.step} of 3 draws revealed`);
    }
    // 07. Render coordination and playback
    function render() {
        const d = reading(), s = cur(), max = maxStep();
        for (const b of document.querySelectorAll('[data-mode]')) {
            const active = b.dataset.mode === state.mode;
            b.classList.toggle('active', active);
            b.setAttribute('aria-pressed', String(active));
        }
        $('rune-stick-stage').hidden = state.mode !== 'sticks';
        $('rune-pouch-stage').hidden = state.mode !== 'pouch';
        placeResultsRail();
        txt('rune-source', `${sourceLabel(d)} · ${state.mode === 'sticks' ? 'RC1' : 'ordered draw'}`);
        $('rune-source').hidden = false;
        $('rune-step').max = max;
        $('rune-step').value = s.step;
        txt('rune-progress', `${s.step} / ${max}`);
        $('rune-back').disabled = s.step === 0;
        $('rune-forward').disabled = s.step === max;
        $('rune-end').disabled = s.step === max;
        txt('rune-play', state.timer !== null ? 'Pause' : s.step === max ? 'Replay' : s.step === 0 ? (state.mode === 'pouch' ? 'Reveal' : 'Cast sticks') : 'Play');
        if (state.mode === 'sticks')
            renderSticks(d);
        else
            renderPouch(d);
        provenance(d);
    }
    // Playback clock. Ordinary slots advance normally; detections hold just long enough
    // to be seen, including multiple detections at the same slot. No new randomness.
    const PLAYBACK = Object.freeze({ sticks: 120, pouch: 900, detection: 500 });
    function stop() {
        if (state.timer !== null)
            clearTimeout(state.timer);
        state.timer = null;
        state.pendingFocus = [];
    }
    function go(step) {
        stop();
        cur().step = Math.min(maxStep(), Math.max(0, Number(step)));
        if (state.mode === 'sticks')
            cur().selected = indexTimeline(reading().payload.timeline)[cur().step].selected;
        render();
    }
    function schedulePlayback(delay) {
        state.timer = setTimeout(advancePlayback, delay);
    }
    function advancePlayback() {
        const s = cur();
        if (state.pendingFocus.length) {
            s.selected = state.pendingFocus.shift();
            schedulePlayback(PLAYBACK.detection);
            render();
            return;
        }
        if (s.step >= maxStep()) {
            stop();
            render();
            return;
        }
        s.step++;
        let delay = PLAYBACK[state.mode];
        if (state.mode === 'sticks') {
            const frame = indexTimeline(reading().payload.timeline)[s.step];
            if (frame.additions.length) {
                [s.selected, ...state.pendingFocus] = frame.additions;
                delay = PLAYBACK.detection;
            }
        }
        if (s.step === maxStep() && !state.pendingFocus.length && delay !== PLAYBACK.detection)
            stop();
        else
            schedulePlayback(delay);
        render();
    }
    function play() {
        if (state.timer !== null) {
            stop();
            render();
            return;
        }
        if (cur().step === maxStep()) {
            cur().step = 0;
            cur().selected = null;
        }
        schedulePlayback(PLAYBACK[state.mode]);
        render();
    }
    // 08. Controls and initialization
    function options() { const picker = $('rune-sample'); picker.replaceChildren(); provider.list(state.mode).forEach((d, i) => { const o = el('option', `Sample ${String.fromCharCode(65 + i)}`); o.value = d.reading_id; picker.append(o); }); picker.value = cur().id; }
    for (const b of document.querySelectorAll('[data-mode]'))
        b.onclick = () => { stop(); if (!demo) { if (reading() && b.dataset.mode !== state.mode) { consultation.open(b.dataset.mode); return; } state.mode=b.dataset.mode; consultation.setMode(state.mode); syncMode(); return; } state.mode = b.dataset.mode; options(); render(); };
    $('rune-sample').onchange = e => { stop(); cur().id = e.target.value; cur().step = 0; cur().selected = null; render(); };
    $('rune-back').onclick = () => go(cur().step - 1);
    $('rune-forward').onclick = () => go(cur().step + 1);
    $('rune-end').onclick = () => go(maxStep());
    $('rune-play').onclick = play;
    $('rune-step').oninput = e => go(e.target.value);
    document.addEventListener('visibilitychange', () => { if (document.hidden) {
        stop();
        if (reading()) render();
    } });
    initPalette();
    ring();
    function syncMode(){ for (const b of document.querySelectorAll('[data-mode]')) { const active=b.dataset.mode===state.mode; b.classList.toggle('active',active); b.setAttribute('aria-pressed',String(active)); } }
    if(demo){ options(); render(); $('rune-reading-body').hidden=false; }
    else {
        const present = d => {
            validateFixture(d,d.mode,true,true); // Validate entire RC1 chronology before committing the UI.
            stop(); fixtures=[d]; state.mode=d.mode; state[d.mode]={id:d.reading_id,step:0,selected:null};
            state[d.mode==='pouch'?'sticks':'pouch']={id:null,step:0,selected:null};
            $('rune-reading-body').hidden=false; txt('rune-provider-status','Reading assigned · play to reveal');
            consultation.setMode(d.mode); syncMode(); render();
        };
        consultation=window.GnosisRuneConsultation.init({showReading:present,onMode:m=>{if(!reading()){state.mode=m;syncMode();}},onPending:()=>{stop(); $('rune-reading-body').hidden=true; $('rune-source').hidden=true;txt('rune-provider-status','Reading pending');},onFailure:()=>{stop();$('rune-reading-body').hidden=true;$('rune-source').hidden=true;txt('rune-provider-status','Reading unavailable');}});
        if(query.has('reading')) consultation.loadSaved(query.get('reading'));
    }
    txt('rune-disclaimer',demo ? 'Synthetic demonstration only. No account, credit or quantum hardware request is made. Replay timing is illustrative. The Gnosis syncretic interpretation is a contemporary reflective framework, not a historical reconstruction or prediction. World shares describe recognized symbols, not physical realms.' : 'Replay reveals the assigned reading and never requests new entropy. Source and recognition metadata describe the recorded method. The Gnosis syncretic interpretation is a contemporary reflective framework, not a historical reconstruction or prediction. World shares describe recognized symbols, not physical realms.');
    for (const b of document.querySelectorAll('[data-mode]')) b.disabled=false;
})();
