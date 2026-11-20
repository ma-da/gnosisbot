/** Gnosis account auth client. Never sends, logs, or persists private signing keys. */
const ROOT = '/api/v1';
const encoder = new TextEncoder();

export function encodeB64url(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
export function decodeB64url(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error('Invalid key encoding');
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4);
  const decoded = Uint8Array.from(atob(padded), c => c.charCodeAt(0));
  if (encodeB64url(decoded) !== value) throw new Error('Noncanonical key encoding');
  return decoded;
}
async function request(path, { method = 'GET', body } = {}) {
  const response = await fetch(ROOT + path, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof result.detail === 'string' ? result.detail : `Account request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return result;
}
export async function publicAccountId(publicB64) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', decodeB64url(publicB64)));
  return [...digest].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
export async function generateAccountKey() {
  if (!globalThis.crypto?.subtle) throw new Error('A secure browser context (HTTPS or localhost) is required.');
  const pair = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
  const publicKey = encodeB64url(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)));
  // PKCS#8 is a standard portable Ed25519 private-key encoding, not a 32-byte seed.
  const privateKey = encodeB64url(new Uint8Array(await crypto.subtle.exportKey('pkcs8', pair.privateKey)));
  return { format: 'gnosis.account-key.v1', algorithm: 'Ed25519', public_key: publicKey, private_key: privateKey };

}
export function parseKeyInput(raw) {
  const value = raw.trim();
  if (value.startsWith('{')) {
    const parsed = JSON.parse(value);
    if (parsed.format !== 'gnosis.account-key.v1' || parsed.algorithm !== 'Ed25519' ||
        typeof parsed.public_key !== 'string' || typeof parsed.private_key !== 'string') {
      throw new Error('Not a Gnosis Ed25519 key file');
    }
    return { public_key: parsed.public_key, private_key: parsed.private_key };
  }
  // Portable single-line credential, containing a PUBLIC key and PRIVATE PKCS#8.
  // Including the public key avoids unsafe/unsupported public derivation in Web Crypto.
  const parts = value.split('.');
  if (parts.length === 3 && parts[0] === 'gnosis1' &&
      decodeB64url(parts[1]).length === 32 && decodeB64url(parts[2]).length === 48) {
    return { public_key: parts[1], private_key: parts[2] };
  }
  throw new Error('Paste your gnosis1 key string, full key-file JSON, or upload your .key file');
}
export async function loginWithKeyFile(rawText) {
  const keyFile = parseKeyInput(rawText);
  if (decodeB64url(keyFile.public_key).length !== 32) throw new Error('Invalid public key length');
  const privateCryptoKey = await crypto.subtle.importKey(
    'pkcs8', decodeB64url(keyFile.private_key), { name: 'Ed25519' }, false, ['sign']
  );
  // Validate that the private key and stated public key correspond by signing
  // and verifying a local nonce BEFORE asking the server to authenticate.
  const publicCryptoKey = await crypto.subtle.importKey(
    'raw', decodeB64url(keyFile.public_key), { name: 'Ed25519' }, false, ['verify']
  );
  const localChallenge = crypto.getRandomValues(new Uint8Array(32));
  const localSig = await crypto.subtle.sign('Ed25519', privateCryptoKey, localChallenge);
  if (!await crypto.subtle.verify('Ed25519', publicCryptoKey, localSig, localChallenge)) {
    throw new Error('The private and public keys do not correspond');
  }
  const account_id = await publicAccountId(keyFile.public_key);
  const challenge = await request('/auth/challenge', { method: 'POST', body: { account_id } });
  const signature = encodeB64url(new Uint8Array(
    await crypto.subtle.sign('Ed25519', privateCryptoKey, encoder.encode(challenge.message))
  ));
  // Never send the private key or original file to server.
  await request('/auth/verify', { method: 'POST', body: {
    account_id, challenge_id: challenge.challenge_id, message: challenge.message, signature
  }});
  return getAccount();
}
export async function registerAccount(publicKey, invitation = null) {
  return request('/accounts/register', {
    method: 'POST', body: { public_key: publicKey, invitation: invitation || null }
  });
}
export async function getAccount() {
  try { return await request('/accounts/me'); }
  catch (error) { if (error.status === 401) return null; throw error; }
}
export async function logoutAccount() {
  return request('/auth/logout', { method: 'POST' });
}
