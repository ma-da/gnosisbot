"""Backward-compatible credit display data.

Schema semantics: available=spendable, reserved=locked, total=available+reserved.
Never treat a reservation as a completed charge.
"""

def credit_view(account):
    spendable = int(account['available'])
    locked = int(account['reserved'])
    if spendable < 0 or locked < 0:
        raise ValueError('Invalid account credit state')
    return {
        'credits': spendable + locked,  # total owned; legacy UI expects `credits`
        'total': spendable + locked,
        'available': spendable,
        'locked': locked,
        'reserved': locked,  # legacy field
    }
