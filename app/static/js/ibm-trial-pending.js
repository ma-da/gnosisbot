// Admin-only IBM trial status. No paid submission, contact information or credits changed here.
const status = document.getElementById('ibm-trial-message');
const open = document.getElementById('ibm-trial-open');
const id = new URLSearchParams(location.search).get('id') || '';
async function refresh() {
  if (!/^[a-f0-9]{32}$/.test(id)) { status.textContent = 'Invalid reading identifier.'; return; }
  try {
    const response = await fetch('/api/v1/consultations/' + encodeURIComponent(id),
      {credentials:'same-origin', cache:'no-store'});
    if (response.status === 401) { status.textContent = 'Sign in to your account to check this reading.'; return; }
    if (!response.ok) throw new Error('Status unavailable ('+response.status+')');
    const data = await response.json();
    if (data.status === 'completed') {
      status.textContent = 'Your IBM reading is complete. Its 128-shot archive is saved.';
      open.hidden = false;
      open.href = '/quantum-oracle.html?reading=' + encodeURIComponent(id);
    } else if (data.status === 'failed' || data.status === 'cancelled') {
      status.textContent = 'This request did not complete. Check your account balance and contact support.';
      open.hidden = true;
    } else {
      status.textContent = 'Request is pending IBM execution or result verification. No further action is required in the browser.';
      open.hidden = true;
    }
  } catch(e) {status.textContent = e.message || 'Unable to check status';}
}
document.getElementById('ibm-trial-refresh').addEventListener('click', () => {void refresh();});
void refresh();
