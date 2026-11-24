"""Promotional credit allocations layered on the existing authoritative ledger.

Supply = ordinary ledger issuances + allocated invitations - completed burns.
An allocated invitation redemption moves existing supply to an account; it is
not a new mint. No direct balance mutations outside identity/transactions.
"""
import hashlib
from uuid import uuid4
from .identity import now, iso, create_invitation, _grant_in_transaction

GROUPS=('Alpha Test','Media','Promo')


def _require_actor(db, actor):
    row=db.execute("SELECT is_admin,status FROM accounts WHERE account_id=?",(actor,)).fetchone()
    if not row or row['status']!='active' or row['is_admin']!=1:
        raise ValueError('Active administrator required')


def create_batch(db, *, actor, group, quantity, credits_each, expires_days, idem):
    if group not in GROUPS:
        raise ValueError('Unknown claim-code group')
    if type(quantity) is not int or not 1<=quantity<=100:
        raise ValueError('Quantity must be 1..100')
    if type(credits_each) is not int or not 1<=credits_each<=100000:
        raise ValueError('Credits per code must be 1..100000')
    if type(expires_days) is not int or not 1<=expires_days<=365:
        raise ValueError('Expiration must be 1..365 days')
    if not isinstance(idem,str) or not 16<=len(idem)<=128:
        raise ValueError('Invalid idempotency key')
    db.execute('BEGIN IMMEDIATE')
    try:
        _require_actor(db,actor)
        prev=db.execute('SELECT * FROM gnosis_credit_batches WHERE idempotency_key=?',(idem,)).fetchone()
        if prev:
            if (prev['campaign_group'],prev['quantity'],prev['credits_each'],prev['expires_days'],prev['created_by']) != (group,quantity,credits_each,expires_days,actor):
                raise RuntimeError('Idempotency key reused for different batch')
            # Codes cannot be reconstructed; never silently issue replacement tokens.
            db.commit()
            return {'already_created':True,'batch_id':prev['batch_id'],'codes':[],
                    'warning':'Batch already issued. Claim-code plaintext was displayed only once.'}
        batch=uuid4().hex
        stamp=iso(now())
        db.execute('INSERT INTO gnosis_credit_batches VALUES(?,?,?,?,?,?,?,?)',
                   (batch,idem,group,quantity,credits_each,expires_days,actor,stamp))
        codes=[]
        for _ in range(quantity):
            # Invitation account_group is a permissions/account cohort, NOT the campaign label.
            token=create_invitation(db,'standard',credits_each,expires_days)
            # create_invitation stores SHA256(decoded token), so use that form for lookup.
            from .identity import b64d
            th=hashlib.sha256(b64d(token,32)).hexdigest()
            invitation=db.execute('SELECT invitation_id FROM invitations WHERE token_hash=?',(th,)).fetchone()
            db.execute('INSERT INTO gnosis_credit_allocations VALUES(?,?,?,?,?,?,?,?,?)',
                       (uuid4().hex,invitation['invitation_id'],group,batch,credits_each,stamp,None,None,actor))
            codes.append(token)
        db.commit()
        return {'already_created':False,'batch_id':batch,'group':group,'quantity':quantity,
                'credits_each':credits_each,'expires_days':expires_days,'codes':codes}
    except Exception:
        db.rollback()
        raise


def redeem_existing(db, *, account_id, token):
    """Redeem an issued invitation to an already registered active account."""
    from .identity import b64d
    if not isinstance(token,str):
        raise ValueError('Invalid claim code')
    token_hash=hashlib.sha256(b64d(token,32)).hexdigest()
    db.execute('BEGIN IMMEDIATE')
    try:
        account=db.execute('SELECT status FROM accounts WHERE account_id=?',(account_id,)).fetchone()
        if not account or account['status']!='active':
            raise ValueError('Account unavailable')
        invitation=db.execute('SELECT * FROM invitations WHERE token_hash=?',(token_hash,)).fetchone()
        stamp=iso(now())
        if not invitation or invitation['revoked_at'] or invitation['redeemed_at'] or invitation['expires_at']<=stamp:
            raise ValueError('Invalid, expired or used claim code')
        alloc=db.execute('SELECT * FROM gnosis_credit_allocations WHERE invitation_id=?',
                         (invitation['invitation_id'],)).fetchone()
        if not alloc or alloc['redeemed_at']:
            raise ValueError('Code is not an allocated promotional claim')
        if invitation['credits'] != alloc['amount']:
            raise RuntimeError('Allocation amount mismatch')
        updated=db.execute('UPDATE invitations SET redeemed_at=?,redeemed_by=? WHERE invitation_id=? AND redeemed_at IS NULL AND revoked_at IS NULL',
                           (stamp,account_id,invitation['invitation_id']))
        if updated.rowcount!=1:
            raise RuntimeError('Already redeemed')
        db.execute('UPDATE gnosis_credit_allocations SET redeemed_at=?,redeemed_by=? WHERE invitation_id=? AND redeemed_at IS NULL',
                   (stamp,account_id,invitation['invitation_id']))
        _grant_in_transaction(db,account_id,alloc['amount'],'invitation',invitation['invitation_id'],
                              'invitation:'+invitation['invitation_id'])
        db.commit()
        return {'redeemed':True,'credits':alloc['amount']}
    except Exception:
        db.rollback()
        raise


def summary(db):
    """Balance/supply reconciliation; all data from primary SQLite, no snapshots."""
    # A credit_ledger grant linked to an allocated invitation is a transfer, not issuance.
    issued=db.execute('''SELECT COALESCE(SUM(l.available_delta + l.reserved_delta),0)
      FROM credit_ledger l WHERE l.kind='grant'
      AND NOT EXISTS (SELECT 1 FROM gnosis_credit_allocations a
        WHERE l.idempotency_key='invitation:'||a.invitation_id)''').fetchone()[0]
    allocations=db.execute('SELECT COALESCE(SUM(amount),0) FROM gnosis_credit_allocations').fetchone()[0]
    burned=db.execute("SELECT COALESCE(-SUM(available_delta+reserved_delta),0) FROM credit_ledger WHERE kind IN ('settle','charge')").fetchone()[0]
    # Nonstandard adjustments/refunds can change supply; expose them explicitly, never hide them.
    other=db.execute("SELECT COALESCE(SUM(available_delta+reserved_delta),0) FROM credit_ledger WHERE kind NOT IN ('grant','settle','charge','reserve','release')").fetchone()[0]
    active_accounts=db.execute('SELECT COALESCE(SUM(available+reserved),0) FROM credit_accounts').fetchone()[0]
    unclaimed=db.execute('''SELECT COALESCE(SUM(a.amount),0) FROM gnosis_credit_allocations a
       JOIN invitations i ON i.invitation_id=a.invitation_id
       WHERE a.redeemed_at IS NULL''').fetchone()[0]
    created=int(issued+allocations+max(other,0))
    destroyed=int(burned+max(-other,0))
    active=int(active_accounts+unclaimed)
    groups=[dict(group=r[0],codes=r[1],unclaimed=r[2],credits_unclaimed=r[3]) for r in db.execute('''
      SELECT a.campaign_group,COUNT(*),SUM(CASE WHEN a.redeemed_at IS NULL THEN 1 ELSE 0 END),
      SUM(CASE WHEN a.redeemed_at IS NULL THEN a.amount ELSE 0 END)
      FROM gnosis_credit_allocations a GROUP BY a.campaign_group ORDER BY a.campaign_group''')]
    return dict(created=created,destroyed=destroyed,active=active,
        accounts_active=int(active_accounts),unclaimed=int(unclaimed),
        reconciliation_difference=int(created-destroyed-active),
        min_ibm_seconds=active*0.3,min_replay_inventory=(active+4)//5,
        groups=groups,adjustment_net=int(other))


def batches(db, limit=100):
    return [dict(r) for r in db.execute('''SELECT b.batch_id,b.campaign_group,b.quantity,b.credits_each,b.expires_days,b.created_at,
      COUNT(a.allocation_id) AS allocations,
      SUM(CASE WHEN a.redeemed_at IS NOT NULL THEN 1 ELSE 0 END) AS redeemed
      FROM gnosis_credit_batches b LEFT JOIN gnosis_credit_allocations a ON a.batch_id=b.batch_id
      GROUP BY b.batch_id ORDER BY b.created_at DESC LIMIT ?''',(limit,))]


def accounts(db, limit=50):
    return [dict(r) for r in db.execute('''SELECT a.account_id,a.status,a.account_group,ca.available,ca.reserved,
      COALESCE((SELECT -SUM(l.available_delta+l.reserved_delta) FROM credit_ledger l WHERE l.account_id=a.account_id AND l.kind IN ('settle','charge')),0) AS spent
      FROM accounts a JOIN credit_accounts ca ON ca.account_id=a.account_id
      ORDER BY (ca.available+ca.reserved) DESC,a.account_id LIMIT ?''',(limit,))]


def leaderboard(db, limit=50):
    return [dict(r) for r in db.execute('''SELECT account_id,COUNT(*) AS completed_charges,
      -SUM(available_delta+reserved_delta) AS credits_spent FROM credit_ledger
      WHERE kind IN ('settle','charge') GROUP BY account_id
      ORDER BY credits_spent DESC,completed_charges DESC LIMIT ?''',(limit,))]
