/** Authentication adapter used by consultation-modal.js. */
import { getAccount, loginWithKeyFile } from './account-auth.js?v=1';
export async function lookupConsultationAccount({ accountCode, keyFile } = {}) {
  if (keyFile && keyFile.size > 4096) throw new Error('Key file too large (4 KB maximum)');
  const provided = keyFile ? await keyFile.text() : (accountCode || '');
  const account = provided.trim() ? await loginWithKeyFile(provided) : await getAccount();
  if (!account) return { verified: false, message: 'Sign in using your private key or visit /account.html to create an account.' };
  return { verified: true, credits: account.available ?? account.credits, account_id: account.account_id };
}
