import {attachIchingInventory} from './inventory-status.js?v=1';
/**
 * GNOSIS.BOT consultation UI, frontend only.
 * No secret is persisted or submitted without a caller-provided lookup function.
 * No successful quantum operations are simulated.
 */
export function initConsultation({ lookupAccount = null, onSubmit = null } = {}) {
  const get = id => document.getElementById(id);
  const dialog = get('consultation-dialog');
  const form = get('consultation-form');
  if (!dialog || !form) throw new Error('Consultation HTML fragment is missing.');
  const account = get('consultation-account');
  const keyFile = get('consultation-key-file');
  const balance = get('consultation-balance');
  const auth = get('consultation-auth');
  const emailWrap = get('consultation-email-wrap');
  const qrng = get('consultation-qrng');
  const email = get('consultation-email');
  const filename = get('consultation-filename');
  const price = get('consultation-price');
  const submit = get('consultation-submit');
  const message = get('consultation-message');
  const costs = { classic: 0, qrng: 0, past: 5, future: 10 };
  const labels = { classic: 'Consult the Oracle', qrng: 'Sample Quantum Noise', past: 'Draw From the IBM Archive', future: 'Measure the Qubits' };
  let verifiedCredits = null;
  let sessionVerified = false;
  // gnosis-m4f-session-adapter-v1
  let requestSerial = 0;
  let lookupTimeout;
  let busy = false;

  const selected = name => form.querySelector(`input[name="${name}"]:checked`)?.value;
  const mode = () => selected('consultation-mode') || 'classic';
  attachIchingInventory({dialog, form, price, mode});
  const needsAccount = () => mode() !== 'classic';
  const minimumCredits = () => mode() === 'qrng' ? 1 : costs[mode()];
  const hasCredentials = () => Boolean(account.value.trim() || keyFile.files?.length || sessionVerified);

  const setMessage = (value, state = 'info') => {
    message.hidden = !value;
    message.textContent = value || '';
    message.dataset.status = state;
  };
  const setBalance = (value, state = 'neutral') => {
    balance.textContent = value;
    balance.dataset.status = state;
  };

  // gnosis-nist-choice-v1
  let qrngProbeSerial = 0;
  async function refreshQuantumSources() {
    if (!qrng) return;
    const selector = 'input[name="consultation-qrng-provider"]';
    const qciOption = form.querySelector(`${selector}[value="qci"]`);
    let nistOption = form.querySelector(`${selector}[value="nist"]`);

    // Support both earlier markup with a disabled NIST choice and versions
    // where only QCI was present. Keep the existing radio group and classes.
    if (!nistOption) {
      const label = document.createElement('label');
      const qciLabel = qciOption?.closest('label');
      if (qciLabel) label.className = qciLabel.className;
      nistOption = document.createElement('input');
      nistOption.type = 'radio';
      nistOption.name = 'consultation-qrng-provider';
      nistOption.value = 'nist';
      nistOption.disabled = true;
      label.append(nistOption, document.createTextNode(' NIST Public Beacon (public randomness)'));
      if (qciLabel?.parentNode) {
        qciLabel.parentNode.insertBefore(label, qciLabel.nextSibling);
      } else {
        qrng.appendChild(label);
      }
    }

    const myProbe = ++qrngProbeSerial;
    nistOption.disabled = true; // Fail closed until the server confirms availability.
    nistOption.title = 'Checking NIST availability';
    try {
      const response = await fetch('/api/v1/services/catalog', {
        credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error(`Service catalog HTTP ${response.status}`);
      const body = await response.json();
      const enabled = body?.services?.some(service =>
        service.service_id === 'iching.qrng_public' && service.available === true);
      if (myProbe !== qrngProbeSerial) return;
      nistOption.disabled = !enabled;
      nistOption.title = enabled
        ? 'Uses the NIST public, timestamped randomness beacon'
        : 'NIST Public Beacon is not enabled on this server';
    } catch (error) {
      if (myProbe !== qrngProbeSerial) return;
      nistOption.disabled = true;
      nistOption.title = 'Unable to check the NIST service';
      console.warn('Gnosis: NIST availability check failed', error);
    }
  }

  function updateView({ clearMessage = true } = {}) {
    auth.hidden = !needsAccount() || sessionVerified;
    emailWrap.hidden = true; // account hub owns verified completion email
    qrng.hidden = mode() !== 'qrng';
    email.required = false;
    price.textContent = `${costs[mode()]} credits${mode() === 'qrng' ? ' · balance ≥1 required' : ''}`;
    submit.textContent = labels[mode()];
    submit.disabled = busy;
    if (needsAccount() && verifiedCredits !== null) {
      const enough = verifiedCredits >= minimumCredits();
      setBalance(`${sessionVerified ? 'Signed in · ' : ''}${verifiedCredits} credits available${enough ? '' : ' · insufficient for this mode'}`, enough ? 'verified' : 'error');
    }
    if (clearMessage) setMessage('');
  }
  function invalidateVerification() {
    requestSerial++;
    clearTimeout(lookupTimeout);
    verifiedCredits = null;
    sessionVerified = false;
    setBalance('Account not yet verified.');
  }
  async function verifyAccount(serial) {
    // Lookup may use the existing HttpOnly session cookie without a keyfile.
    if (typeof lookupAccount !== 'function') {
      setBalance('Balance lookup awaits backend connection.');
      return;
    }
    setBalance('Checking account…');
    try {
      const result = await lookupAccount({
        accountCode: account.value.trim() || null,
        keyFile: keyFile.files?.[0] || null
      });
      if (serial !== requestSerial) return;
      if (!result || result.verified !== true || !Number.isFinite(Number(result.credits))) {
        verifiedCredits = null;
        sessionVerified = false;
        auth.hidden = !needsAccount();
        setBalance(result?.message || 'Sign in with your account key to continue.', 'error');
        return;
      }
      verifiedCredits = Number(result.credits);
      sessionVerified = true;
      auth.hidden = true;
      window.dispatchEvent(new Event('gnosis:account-session-changed'));
      // A successful login leaves only a revocable cookie, not a credential in the form.
      account.value = '';
      keyFile.value = '';
      filename.hidden = true;
      filename.textContent = '';
      const enough = verifiedCredits >= minimumCredits();
      setBalance(`${sessionVerified ? 'Signed in · ' : ''}${verifiedCredits} credits available${enough ? '' : ' · insufficient for this mode'}`, enough ? 'verified' : 'error');
    } catch (error) {
      if (serial !== requestSerial) return;
      verifiedCredits = null;
      sessionVerified = false;
      auth.hidden = !needsAccount();
      setBalance('Account lookup unavailable. Please try again.', 'error');
    }
  }
  function scheduleLookup() {
    invalidateVerification();
    if (!hasCredentials()) return;
    const serial = requestSerial;
    setBalance('Checking account…');
    lookupTimeout = setTimeout(() => { void verifyAccount(serial); }, 600);
  }

  form.querySelectorAll('input[name="consultation-mode"]').forEach(radio => {
    radio.addEventListener('change', () => {
      updateView();
      if (needsAccount() && verifiedCredits === null && !account.value.trim() && !keyFile.files?.length) {
        const serial = ++requestSerial;
        void verifyAccount(serial);
      }
    });
  });
  account.addEventListener('input', () => {
    if (account.value.trim() && keyFile.value) {
      keyFile.value = '';
      filename.hidden = true;
      filename.textContent = '';
    }
    scheduleLookup();
  });
  keyFile.addEventListener('change', () => {
    if (keyFile.files?.length) account.value = '';
    filename.hidden = !keyFile.files?.length;
    filename.textContent = keyFile.files?.length ? `Selected file: ${keyFile.files[0].name}` : '';
    scheduleLookup();
  });
  get('consultation-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right ||
        event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (needsAccount()) {
      if (!hasCredentials()) { setMessage('Enter your account code or select your key file.', 'error'); return; }
      if (verifiedCredits === null) { setMessage('Account verification is required before submitting.', 'error'); return; }
      if (verifiedCredits < minimumCredits()) { setMessage('Insufficient credits for this casting method.', 'error'); return; }
    }
    if (mode() === 'future' && !emailWrap.hidden && !email.checkValidity()) {
      setMessage('Enter a valid email address to receive your results.', 'error');
      email.focus(); return;
    }
    if (get('consultation-research-consent').checked && !get('consultation-question').value.trim()) {
      setMessage('Enter a question to opt into public research, or uncheck the box.', 'error');
      get('consultation-question').focus();
      return;
    }
    const inquiry = {
      question: get('consultation-question').value,
      researchPublicationConsent: get('consultation-research-consent').checked,
      inquiryStyle: selected('consultation-style'),
      mode: mode(),
      qrngProvider: mode() === 'qrng' ? selected('consultation-qrng-provider') : null,
      accountCode: needsAccount() ? (account.value.trim() || null) : null,
      keyFile: needsAccount() ? (keyFile.files?.[0] || null) : null,
      email: null // notifications use the verified account contact
    };
    if (typeof onSubmit !== 'function') {
      setMessage('Frontend ready. Casting backend has not been connected yet.');
      return;
    }
    busy = true;
    updateView({ clearMessage: false });
    try {
      // Caller is responsible for securely storing authorized inquiry metadata.
      // Returning true means it accepted the request; false keeps the dialog open.
      const accepted = await onSubmit(inquiry);
      if (accepted === true) {
        get('consultation-research-consent').checked = false;
        dialog.close();
      }
      else setMessage('This casting method is not connected yet.');
    } catch (error) {
      setMessage(error?.message || 'Unable to start this reading.', 'error');
    } finally {
      busy = false;
      updateView({ clearMessage: false });
    }
  });
  updateView();
  void refreshQuantumSources();
  return {
    open() {
      if (!dialog.open) dialog.showModal();
      void refreshQuantumSources();
      if (needsAccount() && !account.value.trim() && !keyFile.files?.length) {
        // Refresh server session/balance even without a pasted key.
        const serial = ++requestSerial;
        void verifyAccount(serial);
      }
    },
    close() { if (dialog.open) dialog.close(); }
  };
}
