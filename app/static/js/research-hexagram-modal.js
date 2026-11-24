/** Gnosis Research hexagram summary modal. Informational only; never creates a reading. */
const dialog = document.getElementById('research-hexagram-dialog');
const closeButton = document.getElementById('research-hexagram-close');
if (dialog && closeButton) {
  let lastMask = null;
  let lastTrigger = null;
  const text = (id, value) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value == null || value === '' ? '—' : String(value);
  };
  const numeric = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-US') : '—';

  document.addEventListener('gnosis:research-hexagram-open', event => {
    const { hexagram: h, observation: obs, mask } = event.detail ?? {};
    if (!h || !obs || !Number.isInteger(mask) || mask < 0 || mask > 63) return;
    const number = Number(h.king_wen_number ?? h.number);
    if (!Number.isInteger(number) || number < 1 || number > 64) return;
    lastMask = mask;
    lastTrigger = document.activeElement;

    // All corpus-derived strings use textContent, not innerHTML.
    text('research-hex-symbol', h.symbol || String.fromCodePoint(0x4dc0 + number - 1));
    text('research-hex-number', `HEXAGRAM ${String(number).padStart(2, '0')}`);
    text('research-hex-title', h.name || h.title || `Hexagram ${number}`);
    text('research-hex-identity', [h.chinese, h.pinyin].filter(Boolean).join(' · '));
    const tri = h.trigrams || {};
    const lower = tri.lower?.name || tri.lower?.chinese || '—';
    const upper = tri.upper?.name || tri.upper?.chinese || '—';
    text('research-hex-trigrams', `Lower: ${lower} · Upper: ${upper}`);

    text('research-hex-observed', numeric(obs.count));
    text('research-hex-expected', Number.isFinite(obs.expected) ? Number(obs.expected).toFixed(2) : '—');
    text('research-hex-ratio', obs.ratio == null ? '—' : `${Number(obs.ratio).toFixed(2)}×`);
    const phase = document.getElementById('phase-filter');
    text('research-hex-scope', `Aggregate appearances for the current Research filters · ${phase?.selectedOptions?.[0]?.textContent || 'selected reading phase'}`);

    text('research-hex-judgment', h.classical?.judgment_en);
    text('research-hex-image', h.classical?.image_en);
    text('research-hex-taoist-title', h.taoist?.title);
    text('research-hex-taoist-summary', h.taoist?.essence);
    text('research-hex-taoist-modern', h.taoist?.modern_meaning);
    text('research-hex-confucian-title', h.confucian?.title);
    text('research-hex-confucian-summary', h.confucian?.essence);
    text('research-hex-confucian-modern', h.confucian?.modern_meaning);
    text('research-hex-editorial', h.editorial_status || 'AI-assisted interpretations; final human review pending.');

    dialog.querySelectorAll('details').forEach(detail => { detail.open = false; });
    if (!dialog.open) dialog.showModal();
    closeButton.focus({ preventScroll: true });
  });

  closeButton.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    // Clicks on the overlay itself close; clicks inside the panel do not.
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => {
    const tile = lastMask === null ? null : document.querySelector(`#hexagram-matrix .research-tile[data-mask="${lastMask}"]`);
    if (lastTrigger?.isConnected && typeof lastTrigger.focus === 'function') {
      lastTrigger.focus({ preventScroll: true });
    } else {
      tile?.focus({ preventScroll: true });
    }
    lastTrigger = null;
  });
}
