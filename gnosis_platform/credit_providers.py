"""Provider-neutral payment fulfillment interface (future Stripe/Solana integrations).

Providers MUST verify events externally before calling this interface. This module
never calls an external network, accepts wallet signatures, or infers payment finality.
"""
from dataclasses import dataclass
from .identity import _grant_in_transaction

@dataclass(frozen=True)
class VerifiedCreditPurchase:
    provider: str
    external_event_id: str
    account_id: str
    credits: int
    order_id: str


def fulfill_verified_purchase(db, event:VerifiedCreditPurchase):
    """Transactional and idempotent credit issuance AFTER provider-specific verification.

    Provider adapters shall verify Stripe webhook signature, checkout/order association,
    capture status and amount, or Solana chain/transaction/finality/account/asset/amount.
    Integration intentionally not wired to any public route in V1.
    """
    if event.provider not in ('stripe','solana'):
        raise ValueError('Provider not supported')
    if not event.external_event_id or not event.order_id or type(event.credits) is not int or event.credits<=0:
        raise ValueError('Invalid verified purchase')
    db.execute('BEGIN IMMEDIATE')
    try:
        order=db.execute('SELECT account_id,provider,credits,status FROM payment_orders WHERE order_id=?',(event.order_id,)).fetchone()
        if not order or (order['account_id'],order['provider'],order['credits'])!=(event.account_id,event.provider,event.credits):
            raise ValueError('Payment order mismatch')
        if order['status'] not in ('pending','paid'):
            raise ValueError('Payment order not payable')
        idem='payment:'+event.provider+':'+event.external_event_id
        existing=db.execute('SELECT event_id FROM payment_events WHERE provider=? AND external_event_id=?',(event.provider,event.external_event_id)).fetchone()
        if existing:
            db.commit();return False
        from uuid import uuid4
        from .identity import iso,now
        db.execute('INSERT INTO payment_events(event_id,provider,external_event_id,received_at,processed_at) VALUES(?,?,?,?,?)',
                   (uuid4().hex,event.provider,event.external_event_id,iso(now()),iso(now())))
        _grant_in_transaction(db,event.account_id,event.credits,'payment:'+event.provider,event.order_id,idem)
        db.execute("UPDATE payment_orders SET status='completed' WHERE order_id=?",(event.order_id,))
        db.commit();return True
    except Exception:
        db.rollback();raise
