"""Ed25519 account identity, signed one-time challenges, revocable sessions.

No private keys are received or stored. All account mutations occur within
BEGIN IMMEDIATE SQLite transactions. Callers own and close connections.
"""
import base64
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec='microseconds').replace('+00:00','Z')


def b64e(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def b64d(value, n=None):
    if not isinstance(value, str) or len(value) > 4096 or not value:
        raise ValueError('Invalid encoding')
    raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    if b64e(raw) != value or (n is not None and len(raw) != n):
        raise ValueError('Invalid encoding or length')
    return raw


def fingerprint(public_key_b64url):
    return hashlib.sha256(b64d(public_key_b64url, 32)).hexdigest()


def start(db):
    db.execute('BEGIN IMMEDIATE')


def register(db, public_key, invitation_token=None):
    """Register key and (optionally) atomically redeem single-use invitation."""
    account_id = fingerprint(public_key)
    current = iso(now())
    try:
        start(db)
        invitation = None
        if invitation_token is not None:
            token_hash = hashlib.sha256(b64d(invitation_token, 32)).hexdigest()
            invitation = db.execute('SELECT * FROM invitations WHERE token_hash=?', (token_hash,)).fetchone()
            if not invitation or invitation['revoked_at'] or invitation['redeemed_at'] or invitation['expires_at'] <= current:
                raise ValueError('Invalid or expired invitation')
        if db.execute('SELECT 1 FROM accounts WHERE account_id=?', (account_id,)).fetchone():
            raise ValueError('Account already exists')
        group = invitation['account_group'] if invitation else 'standard'
        db.execute('INSERT INTO accounts(account_id, account_group) VALUES(?,?)', (account_id,group))
        db.execute("INSERT INTO account_keys(key_id, account_id, algorithm, public_key_b64url) VALUES(?,?,'Ed25519',?)",
                   (uuid4().hex, account_id, public_key))
        db.execute('INSERT INTO credit_accounts(account_id) VALUES(?)',(account_id,))
        credits = invitation['credits'] if invitation else 0
        if invitation:
            updated = db.execute('UPDATE invitations SET redeemed_at=?, redeemed_by=? WHERE invitation_id=? AND redeemed_at IS NULL AND revoked_at IS NULL',
                                 (current, account_id, invitation['invitation_id']))
            if updated.rowcount != 1:
                raise ValueError('Invitation already claimed')
            if credits:
                _grant_in_transaction(db, account_id, credits, 'invitation', invitation['invitation_id'], 'invitation:'+invitation['invitation_id'])
        db.commit()
        return {'account_id':account_id,'credits':credits}
    except Exception:
        db.rollback()
        raise


def _grant_in_transaction(db, account_id, amount, source, authorized_by, idem):
    if type(amount) is not int or amount <= 0:
        raise ValueError('Credits must be a positive integer')
    inserted = db.execute('INSERT OR IGNORE INTO credit_ledger(entry_id, account_id, kind, available_delta, reserved_delta, idempotency_key, source, authorized_by) VALUES(?,?,?,?,?,?,?,?)',
                          (uuid4().hex, account_id,'grant',amount,0,idem,source,authorized_by))
    if inserted.rowcount:
        db.execute('UPDATE credit_accounts SET available=available+? WHERE account_id=?',(amount,account_id))
    else:
        existing = db.execute('SELECT account_id, available_delta, kind FROM credit_ledger WHERE idempotency_key=?',(idem,)).fetchone()
        if (existing['account_id'],existing['available_delta'],existing['kind']) != (account_id,amount,'grant'):
            raise ValueError('Idempotency key conflict')
    return bool(inserted.rowcount)


def grant(db, account_id, amount, authorized_by, source, idem):
    try:
        start(db)
        account = db.execute("SELECT status FROM accounts WHERE account_id=?",(account_id,)).fetchone()
        if not account or account['status'] != 'active':
            raise ValueError('Unknown or disabled account')
        created = _grant_in_transaction(db,account_id,amount,source,authorized_by,idem)
        db.commit()
        return created
    except Exception:
        db.rollback()
        raise


def create_invitation(db, group, credits, expires_days=14):
    if not isinstance(group,str) or not (1 <= len(group) <= 40) or not group.replace('-','').replace('_','').isalnum():
        raise ValueError('Invalid group')
    if type(credits) is not int or not 0 <= credits <= 1000000 or not (1 <= expires_days <= 365):
        raise ValueError('Invalid invitation policy')
    token = b64e(secrets.token_bytes(32))
    db.execute('INSERT INTO invitations(invitation_id,token_hash,account_group,credits,created_at,expires_at) VALUES(?,?,?,?,?,?)',
               (uuid4().hex,hashlib.sha256(b64d(token,32)).hexdigest(),group,credits,iso(now()),iso(now()+timedelta(days=expires_days))))
    return token


def challenge(db, account_id):
    account = db.execute("SELECT 1 FROM accounts WHERE account_id=? AND status='active'",(account_id,)).fetchone()
    if not account:
        raise ValueError('Unknown or disabled account')
    cid = uuid4().hex
    expires = iso(now()+timedelta(minutes=5))
    # Structured message prevents signature reuse across endpoints/apps.
    message = f'gnosis.bot auth v1\naccount:{account_id}\nchallenge:{cid}\nnonce:{b64e(secrets.token_bytes(32))}\nexpires:{expires}\n'
    db.execute('INSERT INTO auth_challenges(challenge_id,account_id,nonce_hash,expires_at) VALUES(?,?,?,?)',
               (cid,account_id,hashlib.sha256(message.encode()).hexdigest(),expires))
    # Challenge message must be included in reply and supplied again at verification.
    return {'challenge_id':cid,'message':message,'expires_at':expires}


def verify(db, account_id, cid, message, signature):
    current = iso(now())
    try:
        start(db)
        row = db.execute('SELECT * FROM auth_challenges WHERE challenge_id=? AND account_id=?', (cid,account_id)).fetchone()
        if not row or row['used_at'] or row['expires_at'] <= current:
            raise ValueError('Invalid challenge')
        if hashlib.sha256(message.encode()).hexdigest() != row['nonce_hash'] or not message.startswith(f'gnosis.bot auth v1\naccount:{account_id}\nchallenge:{cid}\n'):
            raise ValueError('Invalid challenge')
        keys = db.execute('SELECT public_key_b64url FROM account_keys WHERE account_id=? AND revoked_at IS NULL',(account_id,)).fetchall()
        if not keys or not db.execute("SELECT 1 FROM accounts WHERE account_id=? AND status='active'",(account_id,)).fetchone():
            raise ValueError('Account unavailable')
        sig = b64d(signature,64)
        valid = False
        for key in keys:
            try:
                Ed25519PublicKey.from_public_bytes(b64d(key['public_key_b64url'],32)).verify(sig,message.encode())
                valid = True
                break
            except InvalidSignature:
                pass
        if not valid:
            raise ValueError('Invalid signature')
        db.execute('UPDATE auth_challenges SET used_at=? WHERE challenge_id=?',(current,cid))
        sid = uuid4().hex
        token = b64e(secrets.token_bytes(32))
        expiry = iso(now()+timedelta(days=90))
        db.execute('INSERT INTO sessions(session_id,account_id,verifier_hash,created_at,expires_at) VALUES(?,?,?,?,?)',
                   (sid,account_id,hashlib.sha256(token.encode()).hexdigest(),current,expiry))
        db.commit()
        return {'session_token':token,'expires_at':expiry,'account_id':account_id}
    except Exception:
        db.rollback()
        raise


def session_account(db, token):
    if not isinstance(token,str) or len(token)!=43:
        return None
    hash_value = hashlib.sha256(token.encode()).hexdigest()
    return db.execute('''SELECT a.account_id,a.is_admin,a.account_group,ca.available,ca.reserved,s.session_id
       FROM sessions s JOIN accounts a ON a.account_id=s.account_id
       JOIN credit_accounts ca ON ca.account_id=a.account_id
       WHERE s.verifier_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
       AND a.status='active' ''',(hash_value,iso(now()))).fetchone()


def revoke(db, token):
    db.execute('UPDATE sessions SET revoked_at=? WHERE verifier_hash=? AND revoked_at IS NULL',
               (iso(now()),hashlib.sha256(token.encode()).hexdigest()))
