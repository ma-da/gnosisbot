/**
 * GNOSIS.BOT — Visual Alpha 0.6 controller
 *
 * Explicit reveal policy:
 *   TRUE QUANTUM: ambient → Quantum Reading (Now) → Becoming (on click).
 *   CLASSIC: a fresh single browser-crypto casting → Now → Becoming (on click).
 *   Q RANDOM: unavailable until a real quantum entropy provider is connected.
 *
 * IMPORTANT: only historical archived demo shots may be ranked or explored.
 * A future live/one-time quantum reading must be assigned before inspection.
 */
import {CONFIG} from './config.js?v=0.6';
import {GnosisViz} from './viz.js?v=0.6';
import {GnosisInterference} from './interference.js?v=0.6';
import {clusterReadings} from './clusters.js?v=0.6';

import {initConsultation} from './consultation-modal.js?v=2';
import {lookupConsultationAccount} from './consultation-auth.js?v=1';
import './oracle-account-status.js?v=1'; // Session badge; avoids HTML patch
const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value ?? '—'; };
const MODE = Object.freeze({
  standard: {
    heading: 'A traditional I Ching reading.',
    subtitle: 'Three coins, six lines, one moment becoming another.',
    source: 'CLASSIC · BROWSER CRYPTO RNG'
  },
  quantum_entropy: {
    heading: 'A quantum entropy reading.',
    subtitle: 'Quantum randomness for a traditional casting.',
    source: 'Q RANDOM · QCI uQRNG · LIVE QUANTUM ENTROPY'
  },
  quantum_hardware: {
    heading: 'A quantum hardware reading.',
    subtitle: 'An archived physical quantum throw, revealed by choice.',
    source: 'TRUE QUANTUM · IBM MARRAKESH ARCHIVE'
  }
});

// Reading lifecycle flags are intentionally separate from the D3 animator.
let mode = 'quantum_hardware';
let current = null;
let phase = 'now';
let index = null;
let revealedNow = false;
let revealingNow = false;
let activeRequest = 0;
let readingRevision = 0;
let featureIndex = 0;
let consultation = null;
let consultationStarted = false;
let currentInquiry = null; // Ephemeral local context; never affects randomness.

const hexByBits = new Map();
const viz = window.d3 ? new GnosisViz($('visual')) : null;
const spectrum = window.d3
  ? new GnosisInterference($('interference'), i => liveIbmBatch ? openIbmAlternative(i) : loadArchived(i))
  : null;
		
// The 128-shot IBM demo is a permanent visual reference, not a source for
// Classic/QCI casts. Keep its rendered SVG, frame and introductory formula.
let shotExplorerGeneration = 0;
let demoArchiveReady = false;
let activeShotSource = null; // null | 'ibm_demo' | 'ibm_future'

function setShotExplorerEnabled(enabled) {
  const explorer = $('archive-explorer');
  const field = $('interference');
  const interactive = Boolean(enabled && spectrum);

  // The section and its animated medoid hint always remain present.
  if (explorer) {
    explorer.hidden = false;
    explorer.classList.toggle('explorer-inactive', !interactive);
    explorer.dataset.shotsInteractive = String(interactive);
  }

  // Disable only the shot graphic, NOT its sibling medoid button/modal.
  if (field) {
    field.inert = !interactive;
    field.setAttribute('aria-disabled', String(!interactive));
    field.setAttribute('aria-label', interactive
      ? 'Select a measured shot to explore another IBM archive reading'
      : 'Historical IBM measurements, shown as an inactive reference for this reading');
  }

  // The D3 selection exists only after the demo catalog has rendered.
  if (!interactive && demoArchiveReady) spectrum?.setSelection(null);
}

function syncShotExplorer() {
  const eligible =
    (activeShotSource === 'ibm_demo' && mode === 'quantum_hardware' && demoArchiveReady) ||
    activeShotSource === 'ibm_future'; // Only set after its entire multi-shot batch is verified.
  setShotExplorerEnabled(eligible);
}

function resetShotExplorer() {
  const generation = ++shotExplorerGeneration;
  activeShotSource = null;
  // Do not call spectrum.clear(), hide #archive-explorer, or remove the intro.
  setShotExplorerEnabled(false);
  return generation;
}

// Reserved for the future complete IBM multi-shot archive integration.
// Incomplete batches never become interactive.
function hasEligibleShotArchive(readingType, archive) {
  return ['ibm_future', 'ibm_demo'].includes(readingType) &&
    archive?.complete === true &&
    Number.isInteger(archive.shot_count) && archive.shot_count >= 2 &&
    Array.isArray(archive.readings) &&
    archive.readings.length === archive.shot_count &&
    archive.readings.every(Boolean);
}

async function loadShotExplorer(readingType, fetchArchive, renderArchive) {
  const generation = resetShotExplorer();
  if (!['ibm_future', 'ibm_demo'].includes(readingType)) return;

  try {
    const archive = await fetchArchive();
    if (generation !== shotExplorerGeneration ||
        !hasEligibleShotArchive(readingType, archive)) return;

    renderArchive(archive);
    if (generation !== shotExplorerGeneration) return;
    activeShotSource = readingType;
    syncShotExplorer();
  } catch (error) {
    if (generation === shotExplorerGeneration) {
      resetShotExplorer();
      console.error('Shot archive unavailable:', error);
    }
  }
}

function updateHero(){
  text('hero-heading', MODE[mode].heading);
  text('hero-subheading', MODE[mode].subtitle);
  text('source-label', MODE[mode].source);

  syncShotExplorer();
  $('next').hidden = !consultationStarted;
  $('next').textContent = 'New Consultation ↗';
  document.querySelector('.switcher').classList.toggle('has-next', consultationStarted);
}

/** The original Now button is relabeled until the first explicit reveal. */
function updateControls(){
  const ready = Boolean(current);
  const hardware = mode === 'quantum_hardware';
  const now = document.querySelector('[data-phase="now"]');
  const becoming = document.querySelector('[data-phase="becoming"]');
  now.textContent = !consultationStarted ? 'Quantum Reading' : (hardware && !revealedNow ? 'Quantum Reading' : 'Now');
  if(liveIbmBatch && hardware && consultationStarted && !revealedNow) now.textContent='Play Your New Reading';

  now.disabled = revealingNow || (consultationStarted && !ready);
  const hasMovingLines =
    Array.isArray(current?.reading?.moving_positions_bottom_to_top) &&
    current.reading.moving_positions_bottom_to_top.length > 0;

  becoming.disabled =
    !ready || !revealedNow || revealingNow || !hasMovingLines;

  const noMovingLines = ready && !hasMovingLines;
  becoming.classList.toggle('no-moving-lines', noMovingLines);
  becoming.title = noMovingLines
    ? 'No moving lines: Now and Becoming are identical.'
    : (revealedNow ? 'Reveal the relating hexagram' : 'Available after Now is revealed');
  if (noMovingLines) {
    becoming.setAttribute('aria-label',
      'Becoming unavailable: no moving lines. Now and Becoming are identical.');
  } else {
    becoming.removeAttribute('aria-label');
  }
  $('replay').disabled = !ready || !revealedNow || revealingNow;
  $('next').disabled = revealingNow;

  for(const button of [now, becoming]){
    const pressed = revealedNow && button.dataset.phase === phase;
    button.classList.toggle('active', pressed);
    button.setAttribute('aria-pressed', String(pressed));
  }
  $('visual').setAttribute('aria-label', hardware && !revealedNow
    ? 'Unrevealed quantum reading: decorative changing placeholder lines, 64 hexagrams, and 24 qubit positions'
    : 'Now and Becoming hexagram instrument with a 64-hexagram ring and 24 computing elements');
}

/** Render interpretation only AFTER a reading has actually been revealed. */
function render(which){
  if(!current || !revealedNow)return;
  phase = which;
  const reading = current.reading;
  const hex = reading[which];
  const interpretation = current.interpretations[which] || {};
  text('interpret-phase', which.toUpperCase());
  text('interpret-title-text', `${String(hex.king_wen_number).padStart(2,'0')} · ${interpretation.name || interpretation.title}`);
  $('interpret-title').setAttribute('aria-label',
    `${interpretation.name || interpretation.title}; ${$('reading-detail-tip').textContent}`);
  text('meaning', interpretation.modern_meaning || '');
  text('question', interpretation.reflection_question || '');
  text('historical', interpretation.historical_core || '');
  text('advice', interpretation.advice || '');
  text('shadow', interpretation.shadow || '');
  updateControls();
}

// Technology copy is derived from the actual loaded reading, never from a UI selector.
function renderTechnologyEmployed() {
  const heading = $('technology-heading');
  const copy = $('technology-copy');
  if (!heading || !copy) return;

  const provenance = current?.provenance ?? {};
  const identity = [
    current?.mode, current?.service_id, current?.provider,
    provenance.provider, provenance.source, provenance.backend,
    provenance.service_id
  ].filter(value => typeof value === 'string').join(' ').toLowerCase();

  let title = 'Technology not yet identified';
  let description = 'The selected reading does not yet include sufficient source metadata to identify the physical technology. See the metadata below for recorded details.';

  if (/qci|uqrng/.test(identity)) {
    title = 'QCI uQRNG · Photonic quantum entropy';
    description = 'Quantum Computing Inc. generates random numbers by measuring the arrival times of individual photons in optical time bins. The received measurements provide the coin outcomes; the six I Ching lines and their transformations are then calculated in software.';
  } else if (/ibm|marrakesh|kingston|fez|quantum_hardware/.test(identity)) {
    title = 'IBM · Superconducting quantum processor';
    const when = current?.demo_only
      ? 'This is a replay of previously recorded hardware measurements.'
      : /future/.test(identity)
        ? 'This completed reading was obtained from an individually requested IBM hardware execution.'
        : /past|archiv/.test(identity)
          ? 'This reading uses previously recorded hardware measurements.'
          : 'The recorded measurement outcomes determine the reading.';
    description = 'IBM quantum processors employ cryogenically cooled superconducting transmon qubits. Precisely controlled microwave signals implement quantum operations; qubit states are read out electronically. ' + when;
  } else if (/local_crypto|browser_crypto|classic|system_random|standard/.test(identity)) {
    title = 'Browser Web Crypto · System randomness';
    description = 'Your browser requests cryptographically secure random values from the operating system. No dedicated quantum measurement is claimed. The three-coin lines and any changing-line results are computed locally in software.';
  }

  heading.textContent = title;
  copy.textContent = description;
}

function renderDetails(){
  if(!current)return;
  renderTechnologyEmployed();
  const reading = current.reading;
  const provenance = current.provenance;
  const hardware = mode === 'quantum_hardware';
  const qci = mode === 'quantum_entropy';

  text('shot-label', qci ? (provenance.provider==='ibm_inventory' ? 'IBM QUANTUM PAST · ONE ARCHIVED SHOT' : (provenance.provider==='nist' ? 'NIST PUBLIC BEACON CAST' : 'LIVE QCI QUANTUM CAST')) : hardware
    ? `ARCHIVED SHOT ${String(provenance.shot_index+1).padStart(3,'0')} / ${provenance.shot_count}`
    : 'LIVE LOCAL THROW');
  const moving = reading.moving_positions_bottom_to_top;
  const flags = hardware ? ` · ${reading.moving_flag_matches}/6 QPU flags agree` :
    (qci && provenance.provider === 'ibm_inventory' && Number.isInteger(reading.moving_flag_matches)
      ? ` · ${reading.moving_flag_matches}/6 QPU flags agree` : '');
  const detail = moving.length
    ? `Changing ${moving.length===1?'line':'lines'}: ${moving.join(', ')}${flags}`
    : `No changing lines · Now and Becoming are the same${flags}`;
  text('reading-detail-tip', detail);

  const audit = $('line-audit');
  audit.replaceChildren();
  for(const line of [...reading.lines].reverse()){
    const row = document.createElement('div');
    row.className = 'audit-row';
    const fields = [String(line.position_bottom_to_top),line.coin_bits,String(line.value),
      hardware ? (line.moving_flag_agrees ? 'Flag agrees' : 'Flag differs') : (qci ? (provenance.provider==='ibm_inventory' ? (line.moving_flag_agrees==null ? 'Flag not captured' : (line.moving_flag_agrees ? 'Flag agrees' : 'Flag differs')) : 'Derived from quantum source bits') : 'Computed locally')];
    fields.forEach((value, i) => {
      const cell = document.createElement('span');
      cell.textContent = value;
      if(i === 3)cell.className = hardware ? (line.moving_flag_agrees ? 'good' : 'error') : 'subtle';
      row.append(cell);
    });
    audit.append(row);
  }

  const panel = $('hardware');
  panel.replaceChildren();
  const entries = hardware ? [
    ['Backend', provenance.backend], ['IBM job', provenance.job_id],
    ['Shot index', provenance.shot_index],
    ['QPU time for entire 128-shot batch', `${provenance.qpu_seconds_for_batch} s`],
    ['Logical qubits', provenance.circuit.logical_qubits],
    ['Native two-qubit depth', provenance.circuit.native_2q_depth],
    ['Native two-qubit gates', provenance.circuit.native_2q_gate_count],
    ['Recorded UTC', provenance.created_utc],
    ['Literary corpus', current?.literary_provenance?.corpus_version || current?.interpretations?.now?.corpus_version]
  ] : (qci && provenance.provider==='ibm_inventory') ? [
    ['Provider', 'IBM Quantum · archived hardware'],
    ['Backend', provenance.backend],
    ['IBM job ID', provenance.external_job_id],
    ['Archived sample index', provenance.sample_index],
    ['Source circuit SHA-256', provenance.circuit_sha256],
    ['Hardware archive approval', provenance.approved_at],
    ['Archive selection', 'First unused, approved hardware measurement'],
    ['Reading saved', 'Yes · one public selected observation']
  ] : qci ? [
    ['Provider', provenance.provider==='nist' ? 'NIST Public Beacon v2' : 'QCI uQRNG'],
    ['Cast time (UTC)', provenance.cast_utc],
    ['Request latency', `${provenance.latency_ms ?? '—'} ms`],
    ['Distribution', provenance.distribution],
    ['Quantum samples', `${provenance.n_samples} × ${provenance.n_bits} bits`],
    ['Entropy SHA-256', provenance.entropy_sha256],
    ['Conversion', provenance.conversion],
    ['Reading saved', 'Yes · private to your account'],
    ['Consultation ID', current.qciConsultationId]
  ] : [
    ['Entropy source', 'window.crypto.getRandomValues()'],
    ['Casting', 'Three independent coin bits per line; six lines'],
    ['Computed flags', 'Local deterministic computation'],
    ['Stored on server', 'No']
  ];
  for(const [name,value] of entries){
    const paragraph = document.createElement('p');
    paragraph.textContent = `${name}: ${value ?? '—'}`;
    panel.append(paragraph);
  }
  text('provenance-heading', hardware ? 'PHYSICAL PROVENANCE' : (qci ? (provenance.provider==='ibm_inventory' ? 'IBM ARCHIVED HARDWARE PROVENANCE' : (provenance.provider==='nist' ? 'NIST BEACON PROVENANCE' : 'QCI QUANTUM PROVENANCE')) : 'CASTING PROVENANCE'));
  text('provenance-intro', hardware
    ? 'Raw measured coin bits define the hexagrams. Additional physically measured moving flags are audited separately, including mismatches.'
    : (qci ? (provenance.provider==='ibm_inventory' ? 'An operator-approved historical IBM hardware sample defines this reading. Moving lines follow the recorded coin bits; physically measured flag disagreements are preserved when available. This unique sample is now consumed.' : (provenance.provider==='nist' ? 'NIST public beacon output was combined deterministically with the saved request ID. The same pulse can serve multiple casts; this is not fresh private entropy per reading.' : 'QCI quantum samples define the six coin lines. Moving lines and relating hexagram are calculated deterministically; this reading is saved privately.')) : 'Local coin bits define the traditional reading. The moving indicators are calculated in your browser.'));
}

function enrichReading(wrapper){
  for(const which of ['now','becoming']){
    wrapper.reading[which].chinese = wrapper.interpretations[which]?.chinese || '';
  }
}

/** Setup but do not reveal a selected IBM archive shot. */
function prepareArchived(wrapper){
  readingRevision++;
  current = wrapper;
  activeShotSource = 'ibm_demo';
  enrichReading(wrapper);
  revealedNow = false;
  revealingNow = false;
  phase = 'now';
  $('reading-content').hidden = false;
  $('reading-sections').hidden = true;
  $('unavailable').hidden = true;
  text('reading-status', 'Archived sample prepared. Press Quantum Reading to reveal Now.');
  viz?.setData(wrapper.reading, {hardware:true, ambient:true});
  syncShotExplorer();
  updateControls();
}

async function loadArchived(n){
  if(mode !== 'quantum_hardware' || !demoArchiveReady)return;
  const request = ++activeRequest;
  current = null;
  revealedNow = false;
  revealingNow = false;
  phase = 'now';
  $('reading-sections').hidden = true;
  viz?.startAmbient();
  text('reading-status', 'Preparing archived demonstration reading.');
  updateControls();
  try{
    const response = await fetch(`/api/v1/demo/readings/${n}`);
    if(!response.ok)throw new Error(`Reading request failed: ${response.status}`);
    const wrapper = await response.json();
    if(request !== activeRequest || mode !== 'quantum_hardware')return;
    index = n;
    prepareArchived(wrapper);
    spectrum?.setSelection(n);
  }catch(error){
    if(request !== activeRequest)return;
    console.error(error);
    text('unavailable', 'Could not load the archived reading.');
    $('unavailable').hidden = false;
    text('reading-status', 'Archive request failed.');
  }
}

/**
 * Only this action reveals the Now result. Becoming is NEVER automatic.
 * Disable other phase actions while the six rows are being assembled.
 */
async function revealNow(){
  if(!current || revealingNow)return;
  const revision = readingRevision;
  revealedNow = true;
  revealingNow = true;
  phase = 'now';
  $('reading-sections').hidden = false;
  renderDetails();
  render('now');
  text('reading-status', 'Revealing Now, from the bottom line upward.');
  try{
    if(viz)await viz.revealNow();
  }finally{
    if(revision === readingRevision){
      revealingNow = false;
      updateControls();
      const movingCount = current?.reading?.moving_positions_bottom_to_top?.length ?? 0;
      text('reading-status', movingCount
        ? 'Now is revealed. Select Becoming to see the changing lines transform.'
        : 'Now is revealed. No moving lines: Becoming is identical and unavailable.');
    }
  }
}

function castingFromBits(bytes){
  const lines = [];
  for(let i=0;i<6;i++){
    const bits = Array.from(bytes.slice(i*3,i*3+3), value => value&1).join('');
    const heads = Array.from(bits).reduce((sum,b) => sum+Number(b),0);
    const value = 6+heads;
    const moving = heads===0 || heads===3;
    lines.push({
      position_bottom_to_top:i+1,coin_bits:bits,heads,value,
      now_yang:value%2===1,becoming_yang:(value%2===1)!==moving,
      moving_classically_verified:moving,moving_flag_physically_measured:null,
      moving_flag_agrees:null
    });
  }
  return lines;
}

/** Classic mode samples one unbiased browser-crypto casting, never cherry-picked. */
function localThrow(){
  if(!globalThis.crypto?.getRandomValues)throw new Error('Cryptographic randomness unavailable');
  const bytes = new Uint8Array(18);
  crypto.getRandomValues(bytes);
  const lines = castingFromBits(bytes);
  const nowBits = lines.map(l=>l.now_yang?'1':'0').join('');
  const becomingBits = lines.map(l=>l.becoming_yang?'1':'0').join('');
  const now = hexByBits.get(nowBits), becoming = hexByBits.get(becomingBits);
  if(!now || !becoming)throw new Error('Hexagram catalog unavailable');
  return {
    schema_version:'gnosis.reading.v1',mode:'local_crypto',demo_only:false,
    reading:{
      now:{king_wen_number:now.number,title:now.title,chinese:now.chinese},
      becoming:{king_wen_number:becoming.number,title:becoming.title,chinese:becoming.chinese},
      lines,line_values_bottom_to_top:lines.map(l=>l.value),
      now_bits_bottom_to_top:nowBits,becoming_bits_bottom_to_top:becomingBits,
      moving_positions_bottom_to_top:lines.filter(l=>l.moving_classically_verified).map(l=>l.position_bottom_to_top),
      moving_flag_matches:null
    },
    interpretations:{now,becoming},
    provenance:{source:'browser_crypto',created_utc:new Date().toISOString()}
  };
}

/** Adapt a stored QCI cast to the same shape as Classic and IBM archive readings.
 * The server's 18 quantum bits and line values are authoritative; never resample.
 */
function qciToOracleWrapper(result){
  const reading = result?.reading;
  const provenance = result?.provenance;
  if(!reading || !['qci','nist','ibm_inventory'].includes(provenance?.provider))throw new Error('Invalid QRNG/IBM Past reading provenance');
  const values = reading.lines;
  const coins = reading.coin_bits_bottom_to_top;
  const hardwareFlags = reading.moving_qpu_bits_bottom_to_top;
  if(hardwareFlags != null && (typeof hardwareFlags!=='string' || !/^[01]{6}$/.test(hardwareFlags)))
    throw new Error('Invalid saved IBM physical moving-line flags');
  if(!Array.isArray(values) || values.length !== 6 ||
     !Array.isArray(coins) || coins.length !== 6){
    throw new Error('Incomplete QCI six-line reading');
  }
  const lines = values.map((value,i)=>{
    const bits = coins[i];
    if(!Number.isInteger(value) || value < 6 || value > 9 ||
       typeof bits !== 'string' || !/^[01]{3}$/.test(bits) ||
       6 + [...bits].reduce((sum,bit)=>sum+Number(bit),0) !== value){
      throw new Error('Invalid quantum coin/line agreement');
    }
    const moving = value === 6 || value === 9;
    return {
      position_bottom_to_top:i+1,coin_bits:bits,
      heads:value-6,value,
      now_yang:value%2===1,
      becoming_yang:(value%2===1)!==moving,
      moving_classically_verified:moving,
      moving_flag_physically_measured:hardwareFlags == null ? null : hardwareFlags[i]==='1',
      moving_flag_agrees:hardwareFlags == null ? null : (hardwareFlags[i]==='1')===moving
    };
  });
  const nowBits = lines.map(l=>l.now_yang?'1':'0').join('');
  const becomingBits = lines.map(l=>l.becoming_yang?'1':'0').join('');
  const moving = lines.filter(l=>l.moving_classically_verified).map(l=>l.position_bottom_to_top);
  if(reading.now_yang_bits_bottom_to_top?.join('') !== nowBits ||
     reading.becoming_yang_bits_bottom_to_top?.join('') !== becomingBits ||
     JSON.stringify(reading.moving_positions_bottom_to_top)!==JSON.stringify(moving)){
    throw new Error('Stored QCI result failed hexagram verification');
  }
  const now = hexByBits.get(nowBits);
  const becoming = hexByBits.get(becomingBits);
  if(!now || !becoming)throw new Error('Hexagram reference catalog is unavailable');
  return {
    schema_version:'gnosis.reading.v1',mode:provenance.provider==='ibm_inventory'?'ibm_past_hardware':(provenance.provider==='nist'?'nist_public_beacon':'qci_quantum_entropy'),demo_only:false,
    reading:{
      now:{king_wen_number:now.number,title:now.title,chinese:now.chinese},
      becoming:{king_wen_number:becoming.number,title:becoming.title,chinese:becoming.chinese},
      lines,line_values_bottom_to_top:values,
      now_bits_bottom_to_top:nowBits,becoming_bits_bottom_to_top:becomingBits,
      moving_positions_bottom_to_top:moving,
      moving_flag_matches:null
    },
    interpretations:{now,becoming},provenance
  };
}

function presentQciReading(result,consultationId){
  liveIbmBatch=null; // Single-shot sources have no 128-shot explorer.
  const wrapper=qciToOracleWrapper(result); // Validation before UI change.
  resetShotExplorer(); // Keep the demo drawing, but make it faint and noninteractive.
  activeRequest++; // Invalidates an in-flight archived demo fetch.
  readingRevision++;
  mode='quantum_entropy';
  current=wrapper;
  current.qciConsultationId=consultationId;
  consultationStarted=true;
  revealedNow=false;
  revealingNow=false;
  phase='now';
  enrichReading(wrapper);
  spectrum?.setSelection(null);
  updateHero();
  if(result?.provenance?.provider === 'ibm_inventory') {
    text('hero-heading', 'An archived IBM quantum reading.');
    text('hero-subheading', 'One original measurement from an approved hardware archive.');
  }
  if(result?.provenance?.provider === 'nist') text('source-label','NIST PUBLIC BEACON · REPRODUCIBLE CAST');
  if(result?.provenance?.provider === 'ibm_inventory') text('source-label',`IBM QUANTUM PAST · ${String(result.provenance.backend).toUpperCase()} · ARCHIVED HARDWARE`);
  $('reading-content').hidden=false;
  $('reading-sections').hidden=true;
  $('unavailable').hidden=true;
  viz?.setData(wrapper.reading,{hardware:result?.provenance?.provider === 'ibm_inventory',ambient:false});
  text('reading-status',result?.provenance?.provider === 'ibm_inventory' ? 'Operator-reviewed archived IBM hardware reading selected. Revealing Now.' : (result?.provenance?.provider === 'nist' ? 'NIST public-beacon cast saved. Revealing Now.' : 'Live QCI reading received and verified. Revealing Now.'));
  updateControls();
  void revealNow(); // Standard branded reveal; Becoming remains user-controlled.
}


/** M4C IBM Future replay — a completed, account-owned 128-shot result.
 * Medoid is authoritative from server; browsing an alternate is read-only.
 * No quality/presentation re-ranking and no credit or research writes here.
 */
let liveIbmBatch = null;
let previousArchiveClusters = null;

function ibmLiveShotWrapper(shotIndex){
  if(!liveIbmBatch) throw new Error('IBM shot archive is unavailable');
  const {shots, source} = liveIbmBatch;
  if(!Number.isInteger(shotIndex) || shotIndex < 0 || shotIndex >= shots.length){
    throw new Error('IBM shot index out of range');
  }
  const shot = shots[shotIndex];
  const coin = shot.coin_bits;
  const flags = shot.moving_qpu_bits;
  if(typeof coin !== 'string' || !/^[01]{18}$/.test(coin) ||
     typeof flags !== 'string' || !/^[01]{6}$/.test(flags)){
    throw new Error('Invalid saved IBM coin or physical flag bits');
  }
  const values = [];
  const lines = [];
  for(let i=0;i<6;i++){
    const bits = coin.slice(i*3,i*3+3);
    const heads = [...bits].reduce((n,b)=>n+Number(b),0);
    const value = 6+heads;
    const moving = value===6 || value===9;
    const measured = flags[i]==='1';
    values.push(value);
    lines.push({
      position_bottom_to_top:i+1, coin_bits:bits, heads, value,
      now_yang:value%2===1, becoming_yang:(value%2===1)!==moving,
      moving_classically_verified:moving,
      moving_flag_physically_measured:measured,
      moving_flag_agrees:moving===measured
    });
  }
  if(Array.isArray(shot.values) && JSON.stringify(values)!==JSON.stringify(shot.values)){
    throw new Error('Archived IBM line values differ from coin measurements');
  }
  const nowBits=lines.map(l=>l.now_yang?'1':'0').join('');
  const becomeBits=lines.map(l=>l.becoming_yang?'1':'0').join('');
  const now=hexByBits.get(nowBits), becoming=hexByBits.get(becomeBits);
  if(!now || !becoming) throw new Error('Hexagram catalog is unavailable');
  const moving=lines.filter(l=>l.moving_classically_verified).map(l=>l.position_bottom_to_top);
  const original=source.provenance;
  return {
    schema_version:'gnosis.reading.v1', mode:'ibm_future_128shot', demo_only:false,
    reading:{
      now:{king_wen_number:now.number,title:now.title,chinese:now.chinese},
      becoming:{king_wen_number:becoming.number,title:becoming.title,chinese:becoming.chinese},
      lines, line_values_bottom_to_top:values,
      now_bits_bottom_to_top:nowBits, becoming_bits_bottom_to_top:becomeBits,
      moving_positions_bottom_to_top:moving,
      moving_flag_matches:lines.filter(l=>l.moving_flag_agrees).length
    },
    interpretations:{now,becoming},
    provenance:{
      provider:'ibm', backend:original.backend, job_id:original.external_job_id,
      shot_index:shotIndex, shot_count:shots.length,
      qpu_seconds_for_batch:original.qpu_seconds_for_batch ?? null,
      created_utc:original.staged_at ?? source.finished_at ?? null,
      circuit:{logical_qubits:24,native_2q_depth:original.native_2q_depth ?? null,
               native_2q_gate_count:original.native_2q_gate_count ?? null},
      circuit_sha256:original.circuit_sha256,
      literary_source:null
    }
  };
}

function openIbmAlternative(shotIndex){
  if(!liveIbmBatch || mode!=='quantum_hardware') return;
  const wrapper=ibmLiveShotWrapper(shotIndex);
  activeRequest++;
  index=shotIndex;
  prepareArchived(wrapper);
  text('reading-status', 'IBM Future measurement prepared. Press Play Your New Reading to reveal Now.');
  spectrum?.setSelection(shotIndex);
}

function presentIbmHistoryReading(saved){
  if(saved.service_id!=='iching.quantum_future' ||
      saved.provider!=='ibm_runtime' || saved.provenance?.provider!=='ibm'){
    throw new Error('Unsupported IBM Future reading source');
  }
  const selection=saved.provenance?.selection;
  const shots=selection?.shots;
  const selected=selection?.selected_shot_index;
  if(!Array.isArray(shots) || shots.length!==128 ||
     !Number.isInteger(selected) || selected<0 || selected>=128 ||
     saved.provenance?.selected_shot_index!==selected){
    throw new Error('The IBM 128-shot archive or medoid selection is incomplete');
  }
  liveIbmBatch={shots,source:saved};
  let catalog;
  try {
    const chosen=ibmLiveShotWrapper(selected);
    if(JSON.stringify(saved.reading?.lines)!==
       JSON.stringify(chosen.reading.line_values_bottom_to_top)){
      throw new Error('Saved medoid does not match the underlying measured shot');
    }
    catalog=shots.map((_,i)=>{
      const wrapper=ibmLiveShotWrapper(i);
      return {index:i,values:wrapper.reading.line_values_bottom_to_top,
              now:wrapper.reading.now.king_wen_number,
              becoming:wrapper.reading.becoming.king_wen_number,
              moving_positions:wrapper.reading.moving_positions_bottom_to_top,
              matches:wrapper.reading.moving_flag_matches};
    });
  } catch(error){liveIbmBatch=null;throw error;}
  consultationStarted=true;
  mode='quantum_hardware';
  const analysis=clusterReadings(catalog,CONFIG.clusterCount);
  spectrum?.render(analysis.clusters,selected);
  index=selected;
  updateHero();
  text('source-label',`TRUE QUANTUM · ${String(saved.provenance.backend || 'IBM').toUpperCase()} · 128 SHOTS`);
  openIbmAlternative(selected);
}

function startClassic(){
  activeShotSource = null;
  setShotExplorerEnabled(false);
  readingRevision++;
  try{
    const wrapper = localThrow();
    current = wrapper;
    revealedNow = true;
    revealingNow = false;
    phase = 'now';
    $('reading-content').hidden = false;
    $('reading-sections').hidden = false;
    $('unavailable').hidden = true;
    viz?.setData(wrapper.reading,{hardware:false,ambient:false});
    renderDetails();render('now');
    void revealNow(); // Assemble Now only. Becoming always requires a click.
  }catch(error){
    console.error(error);
    current = null; revealedNow = false;
    $('reading-sections').hidden = true;
    text('unavailable', 'Local cryptographic RNG unavailable in this browser.');
    $('unavailable').hidden = false;
    updateControls();
  }
}

function selectMode(next){
  // Leaving a stored IBM reading clears its alternative-shot view, and restores
  // the original demonstration cluster map so pulses never refer to stale shots.
  if(liveIbmBatch && previousArchiveClusters){
    spectrum?.render(previousArchiveClusters,featureIndex);
    index=featureIndex;
  }
  liveIbmBatch=null;
  if(!Object.hasOwn(MODE,next))return;
  mode = next;
  activeRequest++;
  readingRevision++;
  current = null;
  revealedNow = false;
  revealingNow = false;
  phase = 'now';
  resetShotExplorer(); // Disables the graphic without deleting it.
  updateHero();
  $('reading-sections').hidden = true;
  $('unavailable').hidden = true;
  updateControls();
  if(next === 'quantum_hardware'){
    if(index===null)index=featureIndex;
    loadArchived(index);
  }else if(next === 'standard'){
    spectrum?.setSelection(null);
    startClassic();
  }else{
    viz?.clear();spectrum?.setSelection(null);
    $('reading-content').hidden = true;
    text('unavailable', 'Q Random is not connected yet. No quantum entropy has been requested.');
    $('unavailable').hidden = false;
    text('shot-label', 'NOT CONNECTED');
    text('reading-status', 'Quantum entropy mode is not configured.');
  }
}

function initMedoidModal() {
  const trigger = $('medoid-formula-trigger');
  const dialog = $('medoid-method-dialog');
  const hint = trigger?.closest('.medoid-hint');

  if (!trigger || !dialog || !hint) return;

  let enableTimer;
  let disableTimer;

  const disable = () => {
    trigger.disabled = true;
  };

  // Start timing when the CSS introduction actually starts.
  hint.addEventListener('animationstart', event => {
    if (
      event.target !== hint ||
      event.animationName !== 'medoid-visibility'
    ) return;

    clearTimeout(enableTimer);
    clearTimeout(disableTimer);

    disable();

    // 25% of 7 seconds: equation is fully resolved.
    enableTimer = setTimeout(() => {
      trigger.disabled = false;
    }, 1750);

    // 78% of 7 seconds: fade-out begins.
    disableTimer = setTimeout(disable, 5460);
  });

  hint.addEventListener('animationend', event => {
    if (
      event.target === hint &&
      event.animationName === 'medoid-visibility'
    ) {
      disable();
    }
  });

  trigger.addEventListener('click', () => {
    if (!trigger.disabled && !dialog.open) {
      dialog.showModal();
    }
  });
		
		// Close when clicking the backdrop, not the dialog content.
		dialog.addEventListener('click', (event) => {
				if (!dialog.open) return;

				const rect = dialog.getBoundingClientRect();

				const clickedOutside =
						event.clientX < rect.left ||
						event.clientX > rect.right ||
						event.clientY < rect.top ||
						event.clientY > rect.bottom;

				if (clickedOutside) {
						dialog.close();
				}
		});		
		
}

function initInteractions(){

  document.querySelector('[data-phase="now"]').addEventListener('click',()=>{
    if (revealingNow) return;
    if (!consultationStarted) { consultation?.open(); return; }
    if (!current) return;
    if (!revealedNow) { void revealNow(); return; }
    render('now');viz?.showPhase('now',true);
    text('reading-status', 'Showing Now.');
  });
  document.querySelector('[data-phase="becoming"]').addEventListener('click',()=>{
    if(!current || !revealedNow || revealingNow ||
       !current.reading.moving_positions_bottom_to_top?.length)return;
    render('becoming');viz?.showPhase('becoming',true);
    text('reading-status', 'Showing Becoming.');
  });
  $('replay').addEventListener('click',()=>{if(current && revealedNow && !revealingNow)void revealNow();});
  $('next').addEventListener('click', () => { if (!revealingNow) consultation?.open(); });
}

async function bootstrap(){
  // gnosis-m4f-oracle-v2
  // GNOSIS CONSULTATION MODAL V2: preserve existing API and visualization.
  consultation = initConsultation({
    lookupAccount: lookupConsultationAccount,
    onSubmit: async inquiry => {
      if (inquiry.mode === 'qrng') {
        const qrngProvider = inquiry.qrngProvider || 'qci';
        if (!['qci','nist'].includes(qrngProvider)) {
          throw new Error('Unsupported QRNG provider.');
        }
        const qrngServiceId = qrngProvider === 'nist'
          ? 'iching.qrng_public' : 'iching.qrng_private';
        const response = await fetch('/api/v1/consultations', {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({
            service_id:qrngServiceId,
            idempotency_key:crypto.randomUUID(),
            question:inquiry.question || '',
            inquiry_style:inquiry.inquiryStyle || 'direct',
            research_publication_consent:false
          })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail?.message || data.detail?.code || 'QCI consultation unavailable');
        }
        const id = data.receipt?.consultation_id;
        if (!id) throw new Error('No consultation receipt returned');
        // Normal destination is the main branded instrument, not a separate viewer.
        // The stored result page and authenticated receipt API remain available.
        let saved = data.result;
        if(data.state === 'pending' || !saved){
          const detail = await fetch('/api/v1/consultations/' + encodeURIComponent(id),
            {credentials:'same-origin',cache:'no-store'});
          if(!detail.ok)throw new Error('Could not retrieve saved QCI reading');
          const receipt=await detail.json();
          if(receipt.status !== 'completed' || !receipt.result){
            throw new Error('Quantum reading is still processing; check consultation history.');
          }
          saved=receipt.result;
        }
        currentInquiry={question:inquiry.question,inquiryStyle:inquiry.inquiryStyle,mode:'qrng'};
        presentQciReading(saved,id);
        return true;
      }
      if (inquiry.mode === 'past') {
        const response = await fetch('/api/v1/consultations', {
          method:'POST', credentials:'same-origin',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            service_id:'iching.quantum_past',
            idempotency_key:crypto.randomUUID(),
            question:inquiry.question || '',
            inquiry_style:inquiry.inquiryStyle || 'direct',
            research_publication_consent:false
          })
        });
        const data = await response.json().catch(() => ({}));
        if(!response.ok) throw new Error(data.detail?.message || data.detail?.code || 'No approved IBM Past samples available');
        if(data.state!=='completed' || !data.result || !data.receipt?.consultation_id)
          throw new Error('Archived hardware reading is not yet available');
        currentInquiry={question:inquiry.question,inquiryStyle:inquiry.inquiryStyle,mode:'past'};
        presentQciReading(data.result,data.receipt.consultation_id);
        return true;
      }
      if (inquiry.mode === 'future') {
        const response = await fetch('/api/v1/ibm-future/admin-trial', {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({
            idempotency_key: crypto.randomUUID(),
            question: inquiry.question || '',
            inquiry_style: inquiry.inquiryStyle || 'direct',
            research_publication_consent: false
          })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.detail?.message || data.detail?.code || 'IBM Future trial unavailable');
        }
        if (!data.consultation_id) throw new Error('Missing consultation receipt');
        window.location.assign('/ibm-trial-pending.html?id=' + encodeURIComponent(data.consultation_id));
        return true;
      }
      if (inquiry.mode !== 'classic') return false; // Paid IBM modes not connected yet.
      // The question and inquiry style are context only, not input to the RNG.
      // Kept in browser memory until an explicit backend recording contract exists.
      currentInquiry = { question: inquiry.question, inquiryStyle: inquiry.inquiryStyle, mode: inquiry.mode };
      consultationStarted = true;
      selectMode('standard'); // Existing browser-crypto cast and Now reveal.
      return true;
    }
  });
  initInteractions();
  initMedoidModal();
  updateHero();
  viz?.startAmbient();
  updateControls();
  try{
    const [hexResponse,catalogResponse] = await Promise.all([
      fetch('/api/v1/hexagrams'),fetch('/api/v1/demo/catalog')
    ]);
    if(!hexResponse.ok || !catalogResponse.ok)throw new Error('Reference data could not be loaded');
    const hexagrams = await hexResponse.json();
    const catalog = (await catalogResponse.json()).readings;
    for(const item of hexagrams)hexByBits.set(item.bits,item);
    viz?.setHexagrams(hexagrams);
				const analysis = clusterReadings(catalog, CONFIG.clusterCount);
				featureIndex = analysis.bestIndex;
				index = featureIndex;

				// Keep the historical 128-shot graphic as a background reference for
				// all readings; only its clickability and visual emphasis change.
				previousArchiveClusters=analysis.clusters;
        spectrum?.render(analysis.clusters, index);
        demoArchiveReady = Boolean(spectrum && catalog.length === 128 && catalog.every(Boolean));
        syncShotExplorer();

        // Run the 7s border + medoid formula on every successful page load,
        // including deep-linked QCI history; do not wait for a reading fetch.
        if (spectrum) $('archive-explorer')?.classList.add('explorer-introduced');

        // Account history deep-link: restore exactly the saved cast; never resample.
        const historicalId = new URLSearchParams(window.location.search).get('reading');
        if(historicalId){
          if(!/^[a-f0-9]{32}$/.test(historicalId)) throw new Error('Invalid saved reading ID');
          const savedResponse = await fetch('/api/v1/accounts/readings/' + historicalId,
            {credentials:'same-origin',cache:'no-store'});
          if(!savedResponse.ok) throw new Error(savedResponse.status === 401
            ? 'Sign in on the Account page to reopen this reading'
            : 'Saved reading unavailable to this account');
          const saved = await savedResponse.json();
          if(saved.provider === 'qci' || saved.provider === 'nist' || saved.provider === 'ibm_inventory'){
            currentInquiry = {question:saved.question,inquiryStyle:saved.inquiry_style,mode:'qrng'};
            presentQciReading({reading:saved.reading,provenance:saved.provenance},historicalId);
          }else if(saved.service_id === 'iching.quantum_future' && saved.provider === 'ibm_runtime'){
            currentInquiry = {question:saved.question,inquiryStyle:saved.inquiry_style,mode:'future'};
            presentIbmHistoryReading(saved);
          }else{
            throw new Error('This saved reading source is not supported by the Oracle');
          }
        }else{
          // Existing archived demo behavior remains the default.
          selectMode('quantum_hardware');
        }

  }catch(error){
    console.error(error);
    text('unavailable',`The app data could not be loaded: ${error.message}`);
    $('unavailable').hidden = false;
    text('reading-status','Could not initialize the reference catalog.');
  }
}

bootstrap();
