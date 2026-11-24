// Native Gnosis contact form. No Formspree requests, no hidden fallbacks.
const form = document.getElementById('contact-form');
const status = document.getElementById('contact-native-status');
if (form && status) {
  const send = form.querySelector('button[type="submit"]');
  form.addEventListener('submit', async event => {
    // Without JavaScript, the form posts to the same-origin native endpoint,
    // which also accepts standard urlencoded submissions.
    event.preventDefault();
    if (send.disabled || !form.reportValidity()) return;
    const fields = new FormData(form);
    const body = {
      name: String(fields.get('name') || ''),
      email: String(fields.get('email') || ''),
      message: String(fields.get('message') || ''),
      website: String(fields.get('website') || '')
    };
    const label = send.textContent;
    send.disabled = true;
    status.hidden = false;
    status.textContent = 'Sending your message…';
    try {
      const response = await fetch('/api/v1/contact', {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!response.ok) {
        const messages = {
          413: 'Message is too long. Please shorten it and try again.',
          422: 'Please check your name, email, and message.',
          429: 'Too many submissions. Please try again later.',
          503: 'Messaging is temporarily unavailable. Please try again later.'
        };
        throw new Error(messages[response.status] || `Message not sent (${response.status}). Please try again.`);
      }
      const data = await response.json();
      if (data.received !== true) throw new Error('The server did not confirm receipt. Please try again.');
      form.reset();
      status.textContent = 'Thank you. Your message has been received.';
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : 'Unable to send your message. Please try again.';
    } finally {
      send.disabled = false;
    }
  });
}
