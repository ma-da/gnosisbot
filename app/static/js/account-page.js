import { generateAccountKey, registerAccount, loginWithKeyFile, getAccount, logoutAccount } from './account-auth.js?v=1';
const $ = id => document.getElementById(id);
let created = null;
const show = (text, bad = false) => { $('status').textContent = text; $('status').dataset.error = String(bad); };
function presentUser(user) {
  $('session').textContent = user ? `Authenticated · ${user.account_id.slice(0, 12)}… · ${user.credits}` : 'No active browser session';
  // gnosis-m2c spendable credit badge
  if (user) {
    const free = document.createElement('span');
    free.style.color = '#16a34a';
    free.style.fontWeight = '600';
    free.textContent = ` (${user.available ?? user.credits})`;
    free.title = 'Credits currently available; excludes locked credits';
    $('session').append(free, document.createTextNode(' credits'));
  }
  $('logout').hidden = !user;
  window.dispatchEvent(new Event('gnosis:account-session-changed'));
}
async function updateSession() {
  try { presentUser(await getAccount()); } catch { show('Unable to check account session.', true); }
}
$('create').addEventListener('click', async () => {
  try {
    created = await generateAccountKey();
    $('key-json').value = JSON.stringify(created, null, 2);
    $('key-string').value = `gnosis1.${created.public_key}.${created.private_key}`;
    $('key-output').hidden = false;
    $('activate').disabled = false;
    show('Key generated in this browser. Download and store it safely before activating.');
  } catch (err) { show(err.message, true); }
});
$('copy-string').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('key-string').value); show('Private key string copied.'); }
  catch { show('Clipboard unavailable; copy key string manually.', true); }
});
$('copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('key-json').value); show('Key file copied to clipboard.'); }
  catch { show('Clipboard unavailable. Select the key and copy manually.', true); }
});
$('download').addEventListener('click', () => {
  if (!created) return;
  const blob = new Blob([$('key-json').value + '\n'], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `gnosis-${created.public_key.slice(0, 12)}.key`;
  anchor.click();
  URL.revokeObjectURL(url);
});
$('activate').addEventListener('click', async () => {
  if (!created || !$('saved').checked) { show('First save your key and confirm you have a backup.', true); return; }
  $('activate').disabled = true;
  try {
    const record = await registerAccount(created.public_key, $('invitation').value.trim());
    show(`Account registered (${record.credits} starting credits). Signing in…`);
    await loginWithKeyFile(JSON.stringify(created));
    await updateSession();
    created = null;
    $('key-json').value = '';
    $('key-string').value = '';
    $('key-output').hidden = true;
    $('saved').checked = false;
    show('Account activated and browser authenticated. Your key is not stored by gnosis.bot.');
  } catch (err) { $('activate').disabled = false; show(err.message, true); }
});
$('login').addEventListener('click', async () => {
  try {
    const file = $('login-file').files?.[0];
    if (file && file.size > 4096) throw new Error('Key file exceeds 4 KB');
    const content = file ? await file.text() : $('login-key').value;
    if (!content.trim()) throw new Error('Paste your key JSON or select a .key file');
    const user = await loginWithKeyFile(content);
    $('login-key').value = '';
    $('login-file').value = '';
    presentUser(user);
    show('Authenticated. Your private key was not sent to the server.');
  } catch (err) { show(err.message, true); }
});
$('logout').addEventListener('click', async () => {
  try { await logoutAccount(); presentUser(null); show('Browser session revoked.'); }
  catch (err) { show(err.message, true); }
});
async function copyAccountId() {
  const response = await fetch('/api/v1/accounts/me', {
    credentials: 'same-origin'
  });

  if (!response.ok) {
    throw new Error(`Account lookup failed: ${response.status}`);
  }

  const data = await response.json();
  const accountId = data.account_id;

  if (!accountId) {
    throw new Error('No account ID returned');
  }

  try {
    await navigator.clipboard.writeText(accountId);
  } catch {
    const temp = document.createElement('textarea');
    temp.value = accountId;
    temp.setAttribute('readonly', '');
    temp.style.position = 'absolute';
    temp.style.left = '-9999px';
    document.body.appendChild(temp);
    temp.select();
    document.execCommand('copy');
    document.body.removeChild(temp);
  }

  const feedback = document.getElementById('copy-account-feedback');
  if (feedback) feedback.textContent = 'Public account ID copied';

  const button = document.getElementById('copy-account-id');
  if (button) {
    const old = button.textContent;
    button.textContent = 'Copied';
    setTimeout(() => {
      button.textContent = old;
    }, 1200);
  }
}

document
  .getElementById('copy-account-id')
  ?.addEventListener('click', () => {
    copyAccountId().catch(err => {
      console.error(err);
      const feedback = document.getElementById('copy-account-feedback');
      if (feedback) feedback.textContent = 'Could not copy account ID';
    });
  });
		
updateSession();

// Account key-file drag and drop; moved from inline HTML.
(() => {
  const zone = document.getElementById('key-dropzone');
  const input = document.getElementById('login-file');
  const feedback = document.getElementById('key-drop-feedback');

  if (zone && input) {
  		let dragDepth = 0;

  		zone.addEventListener('dragenter', event => {
  				if (!event.dataTransfer.types.includes('Files')) return;
  				event.preventDefault();
  				dragDepth++;
  				zone.classList.add('is-dragover');
  		});

  		zone.addEventListener('dragover', event => {
  				event.preventDefault();
  				event.dataTransfer.dropEffect = 'copy';
  		});

  		zone.addEventListener('dragleave', () => {
  				dragDepth--;
  				if (dragDepth <= 0) {
  						dragDepth = 0;
  						zone.classList.remove('is-dragover');
  				}
  		});

  		zone.addEventListener('drop', event => {
  				event.preventDefault();
  				dragDepth = 0;
  				zone.classList.remove('is-dragover');

  				const files = event.dataTransfer.files;

  				if (files.length !== 1) {
  						feedback.textContent = 'Please select one account key file.';
  						return;
  				}

  				const file = files[0];

  				if (!/\.(key|json|txt)$/i.test(file.name)) {
  						feedback.textContent = 'Use a .key, .json, or .txt file.';
  						return;
  				}

  				// Transfer the dropped file into the existing input.
  				const transfer = new DataTransfer();
  				transfer.items.add(file);
  				input.files = transfer.files;

  				// Trigger the existing file-upload handler.
  				input.dispatchEvent(new Event('change', {
  						bubbles: true
  				}));

  				feedback.textContent = `${file.name} selected.`;
  		});

  		input.addEventListener('change', () => {
  				if (input.files.length) {
  						feedback.textContent =
  								`${input.files[0].name} selected.`;
  				}
  		});
  }
})();
