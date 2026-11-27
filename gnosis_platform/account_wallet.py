"""Account-owned verified Solana public-wallet linking; zero wallet secrets/custody.

All signing challenges originate server-side and are bound to the authenticated
Gnosis account, configured web origin, wallet address, and expiration. Signature
verification is Ed25519 over exact UTF-8 challenge bytes (raw signMessage mode).
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .solana_watch import AnkrRpc, RSTORY_MINT, WatchError, valid_pubkey, positive_integer

B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
ACCOUNT_ID = re.compile(r'^[a-f0-9]{64}$')
MAX_CHALLENGES_PER_HOUR = 5
CHALLENGE_SECONDS = 300

class WalletError(ValueError):
    pass

class WalletConflict(WalletError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value=None) -> str:
    return (value or now()).isoformat(timespec='milliseconds').replace('+00:00','Z')


def b58decode(value, expected):
    if not isinstance(value,str) or not (32 <= len(value) <= 96) or any(ch not in B58 for ch in value):
        raise WalletError('Invalid Solana encoding')
    num=0
    for ch in value:
        num=num*58+B58.index(ch)
    prefix=len(value)-len(value.lstrip('1'))
    raw=b'\x00'*prefix + num.to_bytes((num.bit_length()+7)//8,'big')
    if len(raw) != expected:
        raise WalletError('Invalid Solana key or signature length')
    return raw


def active(db, account_id):
    row=db.execute('''SELECT wallet_address,linked_at FROM gnosis_wallet_links
        WHERE account_id=? AND revoked_at IS NULL ORDER BY linked_at DESC LIMIT 1''',
        (account_id,)).fetchone()
    return {'linked':bool(row),'address':row['wallet_address'] if row else None,
            'verified_at':row['linked_at'] if row else None}


def linking_enabled() -> bool:
    return os.environ.get('GNOSIS_ENABLE_WALLET_LINKING') == 'YES'


def _origin():
    origin=os.environ.get('GNOSIS_WEB_ORIGIN','').rstrip('/')
    if not origin.startswith('https://') or any(c in origin for c in ('\n','\r',' ', '?','#')):
        raise WalletError('Wallet registration requires a configured HTTPS Gnosis origin')
    return origin


def issue(db, *, account_id, address):
    if not linking_enabled():raise WalletError('Wallet linking is not enabled')
    if not ACCOUNT_ID.fullmatch(account_id):raise WalletError('Invalid account')
    if not valid_pubkey(address):raise WalletError('Invalid Solana wallet address')
    # Exact canonical 32-byte public key: Solana's base58 representation.
    b58decode(address,32)
    origin=_origin()
    created=now()
    uid=uuid4().hex
    nonce=secrets.token_urlsafe(24)
    issued=stamp(created)
    expires=stamp(created+timedelta(seconds=CHALLENGE_SECONDS))
    message=(f'Gnosis Bot wallet association\nOrigin: {origin}\n'
             f'Gnosis account: {account_id}\nSolana address: {address}\n'
             f'Nonce: {nonce}\nIssued at: {issued}\nExpires at: {expires}\n'
             'Purpose: Verify ownership of a public wallet address. '
             'This does not authorize a transaction, payment, or account login.')
    db.execute('BEGIN IMMEDIATE')
    try:
        hour_ago=stamp(created-timedelta(hours=1))
        n=db.execute('''SELECT count(*) FROM gnosis_wallet_challenges
            WHERE account_id=? AND created_at>=?''',(account_id,hour_ago)).fetchone()[0]
        if n>=MAX_CHALLENGES_PER_HOUR:raise WalletError('Wallet verification rate limit reached')
        db.execute('''INSERT INTO gnosis_wallet_challenges
            (challenge_id,account_id,wallet_address,message,created_at,expires_at)
            VALUES(?,?,?,?,?,?)''',(uid,account_id,address,message,issued,expires))
        db.commit()
    except BaseException:
        db.rollback();raise
    return {'challenge_id':uid,'address':address,'message':message,'expires_at':expires}


def verify_link(db, *, account_id, challenge_id, signature):
    if not linking_enabled():raise WalletError('Wallet linking is not enabled')
    if not re.fullmatch('[a-f0-9]{32}',challenge_id or ''):raise WalletError('Invalid wallet challenge')
    sig=b58decode(signature,64)
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('''SELECT * FROM gnosis_wallet_challenges
            WHERE challenge_id=? AND account_id=? AND consumed_at IS NULL AND expires_at>?''',
            (challenge_id,account_id,stamp())).fetchone()
        if not row:raise WalletError('Wallet challenge invalid, expired, or already used')
        # Reject if the app's configured web origin changed after challenge issuance.
        if f'Origin: {_origin()}\n' not in row['message']:
            raise WalletError('Verification origin changed; reconnect your wallet')
        key=b58decode(row['wallet_address'],32)
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(sig,row['message'].encode('utf-8'))
        except (InvalidSignature,ValueError):
            raise WalletError('Wallet signature could not be verified') from None
        conflicting=db.execute('''SELECT account_id FROM gnosis_wallet_links
            WHERE wallet_address=? AND revoked_at IS NULL''',(row['wallet_address'],)).fetchone()
        if conflicting and conflicting['account_id'] != account_id:
            raise WalletConflict('This wallet is already linked to another Gnosis account')
        current=active(db,account_id)
        moment=stamp()
        if current['linked'] and current['address']!=row['wallet_address']:
            db.execute('''UPDATE gnosis_wallet_links SET revoked_at=?
                WHERE account_id=? AND revoked_at IS NULL''',(moment,account_id))
        if not (current['linked'] and current['address']==row['wallet_address']):
            db.execute('''INSERT INTO gnosis_wallet_links
                (link_id,account_id,wallet_address,linked_at) VALUES(?,?,?,?)''',
                (uuid4().hex,account_id,row['wallet_address'],moment))
        db.execute('''UPDATE gnosis_wallet_challenges SET consumed_at=? WHERE challenge_id=?''',
                   (moment,challenge_id))
        db.commit()
        return active(db,account_id)
    except sqlite3.IntegrityError:
        db.rollback();raise WalletConflict('Wallet is linked to another account') from None
    except BaseException:
        db.rollback();raise


def unlink(db, *, account_id):
    db.execute('BEGIN IMMEDIATE')
    try:
        current=active(db,account_id)
        db.execute('''UPDATE gnosis_wallet_links SET revoked_at=?
            WHERE account_id=? AND revoked_at IS NULL''',(stamp(),account_id))
        db.commit()
        return {'linked':False,'address':None,'verified_at':None,'was_linked':current['linked']}
    except BaseException:
        db.rollback();raise


def balances(db, *, account_id):
    link=active(db,account_id)
    if not link['linked']:raise WalletError('No verified wallet linked')
    # No access to the user's browser wallet or private keys, ever.
    result={'address':link['address'],'network':'mainnet-beta','sol':None,
            'rstory':None,'rstory_mint':RSTORY_MINT, 'as_of':None,'status':'unavailable'}
    if os.environ.get('GNOSIS_ENABLE_WALLET_BALANCES')!='YES':return result
    key=os.environ.get('ANKR_API_KEY') or os.environ.get('GNOSIS_ANKR_API_KEY')
    if not key:return result
    try:
        rpc=AnkrRpc(key,'mainnet-beta')
        sol=rpc.call('getBalance',[link['address'],{'commitment':'confirmed'}])
        lamports=positive_integer(sol['value'])
        tokens=rpc.call('getTokenAccountsByOwner',[
            link['address'],{'mint':RSTORY_MINT},{'encoding':'jsonParsed','commitment':'confirmed'}])
        total=Decimal(0)
        accounts=tokens['value']
        if not isinstance(accounts,list) or len(accounts)>1000:raise WalletError('Invalid token account response')
        for record in accounts:
            info=record['account']['data']['parsed']['info']
            if info['mint']!=RSTORY_MINT or info['owner']!=link['address']:
                raise WalletError('RPC returned unexpected token owner or mint')
            amount=info['tokenAmount']
            raw=positive_integer(amount['amount'])
            decimals=amount['decimals']
            if type(decimals) is not int or not 0<=decimals<=18:raise WalletError('Invalid token decimals')
            total += Decimal(raw)/(Decimal(10)**decimals)
        result.update(sol=format(Decimal(lamports)/Decimal(10**9),'f'),
                      rstory=format(total,'f'),as_of=stamp(),status='ok')
    except (WatchError,ValueError,KeyError,TypeError,IndexError,OverflowError):
        # Never reveal remote URL or API key; never represent unavailable as 0.
        pass
    return result
