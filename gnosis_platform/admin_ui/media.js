// Administrator Media CRM: manual outreach records only; no sending or credits.
(() => {
  const el = id => document.getElementById(id);
  const STATUS = ['researching','ready','contacted','follow_up','responded','published','declined','archived'];
  let entries = [], offset = 0, total = 0, selected = null, active = null, busy = false;
  const PAGE = 40;
  function node(tag, text, className) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = String(text);
    if (className) e.className = className;
    return e;
  }
  function feedback(text, err = false) {
    const target = el('media-feedback');
    target.textContent = text;
    target.classList.toggle('error', err);
  }
  async function request(path, options = {}) {
    const r = await fetch(path, {credentials:'same-origin',cache:'no-store', ...options});
    const value = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(value.detail || (r.status === 401 ? 'Sign in first.' : `Request failed (${r.status}).`));
    return value;
  }
  const escapeQuery = s => encodeURIComponent(s || '');
  async function refresh() {
    if (busy) return;
    busy = true; feedback('Loading media contacts…');
    try {
      const q = escapeQuery(el('media-search').value.trim());
      const status = escapeQuery(el('media-filter').value);
      const data = await request(`/api/v1/admin/media?query=${q}&status=${status}&limit=${PAGE}&offset=${offset}`);
      entries = data.contacts || []; total = data.total || 0;
      render(); feedback(`${total} matching media contact${total === 1 ? '' : 's'}.`);
    } catch (e) { feedback('Unable to load Media CRM: ' + e.message, true); }
    finally { busy = false; }
  }
  function render() {
    const tbody = el('media-rows'); tbody.replaceChildren();
    if (!entries.length) {
      const tr = node('tr'); const td = node('td', 'No matching contacts.');
      td.colSpan = 5; tr.append(td); tbody.append(tr);
    }
    for (const item of entries) {
      const tr = node('tr');
      const who = node('td');
      who.append(node('div', item.name || item.outlet, 'media-contact-name'));
      if (item.name && item.outlet) who.append(node('div', item.outlet));
      if (item.role) who.append(node('small', item.role));
      const stage = node('td'); stage.append(node('span', item.status.replaceAll('_', ' '), 'media-pill'));
      const follow = node('td', item.next_followup || '—');
      const credit = node('td');
      credit.append(node('span', item.claim_code_given ? 'Code given' : 'Not given', item.claim_code_given ? 'media-pill given' : 'media-pill'));
      const actions = node('td'); const buttons = node('div', undefined, 'media-actions');
      const edit = node('button', 'Edit'); edit.type = 'button'; edit.className = 'secondary';
      edit.addEventListener('click', () => openEditor(item));
      const activity = node('button', 'Activity'); activity.type = 'button'; activity.className = 'secondary';
      activity.addEventListener('click', () => showActivity(item));
      buttons.append(edit, activity); actions.append(buttons);
      tr.append(who, stage, follow, credit, actions); tbody.append(tr);
    }
    el('media-range').textContent = `${total ? offset + 1 : 0}–${Math.min(offset+entries.length,total)} of ${total}`;
    el('media-prev').disabled = offset <= 0;
    el('media-next').disabled = offset + PAGE >= total;
  }
  function openEditor(item = null) {
    selected = item;
    const form = el('media-form'); form.reset();
    el('media-dialog-title').textContent = item ? 'Edit media contact' : 'Add media contact';
    for (const name of ['name','outlet','email','role','topics','notes','published_url','status','next_followup']) {
      const field = form.elements.namedItem(name);
      field.value = item ? (item[name] || '') : (name === 'status' ? 'researching' : '');
    }
    form.elements.namedItem('claim_code_given').checked = Boolean(item && item.claim_code_given);
    el('media-editor-feedback').textContent = item && item.claim_code_given_at
      ? `Claim code recorded as given ${item.claim_code_given_at}. No account balances are tracked.`
      : 'Claim-code checkbox records manual provision only; no code is generated or redeemed.';
    el('media-dialog').showModal();
  }
  async function save(e) {
    e.preventDefault();
    const form = el('media-form'); const button = el('media-save'); button.disabled = true;
    const fields = ['name','outlet','email','role','topics','notes','published_url','status','next_followup'];
    const data = {};
    for (const key of fields) data[key] = form.elements.namedItem(key).value.trim();
    if (data.email) data.email = data.email.toLowerCase();
    data.next_followup = data.next_followup || null;
    data.claim_code_given = form.elements.namedItem('claim_code_given').checked;
    data.revision = selected?.revision || 0;
    try {
      const path = selected ? `/api/v1/admin/media/${selected.id}` : '/api/v1/admin/media';
      const method = selected ? 'PUT' : 'POST';
      const updated = await request(path, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
      // Confirm the stored revision by reading it back before telling the user saved.
      const confirmed = await request(`/api/v1/admin/media/${updated.id}`);
      if (confirmed.revision !== updated.revision || fields.some(k => (confirmed[k] || '') !== (data[k] || '')) ||
          confirmed.claim_code_given !== data.claim_code_given) throw new Error('Stored record verification failed');
      el('media-dialog').close(); feedback(`Saved ${confirmed.name || confirmed.outlet} · revision ${confirmed.revision}.`);
      offset = 0; await refresh();
    } catch (err) { el('media-editor-feedback').textContent = 'Save failed: ' + err.message; }
    finally { button.disabled = false; }
  }
  async function showActivity(item) {
    active = item;
    el('media-activity-section').hidden = false;
    el('media-activity-heading').textContent = `Outreach history — ${item.name || item.outlet}`;
    el('media-activity-note').value = '';
    await loadActivity();
  }
  async function loadActivity() {
    const list = el('media-activity-list'); list.replaceChildren();
    if (!active) return;
    try {
      const rows = await request(`/api/v1/admin/media/${active.id}/activity`);
      for (const row of rows) {
        let summary = row.kind.replaceAll('_', ' ');
        if (row.details?.note) summary += ': ' + row.details.note;
        else if (row.details?.changed) summary += ': ' + Object.keys(row.details.changed).join(', ');
        const li = node('li');
        li.append(node('strong', `${row.created_at} · ${summary}`));
        list.append(li);
      }
      if (!rows.length) list.append(node('li', 'No activity recorded.'));
    } catch (e) { list.append(node('li', 'Unable to load activity: ' + e.message)); }
  }
  async function recordActivity() {
    if (!active) return;
    const note = el('media-activity-note').value.trim();
    const kind = el('media-activity-kind').value;
    const button = el('media-add-activity'); button.disabled = true;
    try {
      await request(`/api/v1/admin/media/${active.id}/activity`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note,kind})});
      el('media-activity-note').value = '';
      await loadActivity(); feedback('Outreach activity recorded.');
    } catch (e) { feedback('Activity not saved: ' + e.message, true); }
    finally { button.disabled = false; }
  }
  function init() {
    if (!el('media-crm-root')) return;
    el('media-new').addEventListener('click', () => openEditor());
    el('media-form').addEventListener('submit', save);
    el('media-cancel').addEventListener('click', () => el('media-dialog').close());
    el('media-search-form').addEventListener('submit', e => {e.preventDefault();offset=0;refresh();});
    el('media-filter').addEventListener('change', () => {offset=0;refresh();});
    el('media-prev').addEventListener('click', () => {offset=Math.max(0,offset-PAGE);refresh();});
    el('media-next').addEventListener('click', () => {offset+=PAGE;refresh();});
    el('media-add-activity').addEventListener('click', recordActivity);
    el('media-activity-close').addEventListener('click', () => {active=null;el('media-activity-section').hidden=true;});
    refresh();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
