# Accounts and credit accounting

Ed25519 keys are generated and signed in the browser. The server stores the public key, an account fingerprint (SHA-256), one-time signed challenges and revocable sessions; it never needs the private key. Keep the private credential backed up locally. There is no password reset for a lost key. The HTTP-only session cookie is secure by default and SameSite=Lax; mutation endpoints require the configured exact browser Origin. Owner filtering applies to history, replay, receipts and resonance.

Use `python -m gnosis_platform.provision invitations --count 5 --group alpha --credits 20 --output /var/lib/gnosis/private/invitations.csv` from a service-user shell with the environment loaded. Invitation CSV is private. Registration without an invitation yields a standard zero-credit account. Credit grants use `grant --account-id ID --credits N --reason REASON --idempotency-key UNIQUE`; only an authorized operator can execute it. `make-admin --account-id ID` additionally requires `GNOSIS_PROVISION_ADMIN=YES` for that one CLI process. Never globally arm admin provisioning. No production credit purchases are implemented here.

Server request IDs, idempotency keys, transaction locks, available/reserved balances and append-only credit entries prevent double charging. Consultations may remain pending after uncertain remote execution. Never manufacture receipts, delete pending rows, reset credit balance manually, or retry an ambiguous paid admission. Reconcile through operator tools.

Current service costs: Classic 0, QCI/NIST 0 with minimum balance 1 (cooldown policies apply), IBM Past 5, Future 10 where explicitly admitted. AI enhancement is not available; general Future not enabled. Credits are server-side integer units, not a promise of exchange value.

Email verification encrypts contact addresses, stores masked displays and uses separate single-use confirmation tokens; the worker sends completion messages only where enabled/eligible. Contact-form messages are a separate Formspree interaction. Owner resonance feedback is not financial settlement and can be changed without recasting. See research documentation.
