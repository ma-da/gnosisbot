"""GNOSIS Solana/RSTORY WATCH-ONLY scanner.

No wallet signing, payment matching, order fulfillment, credit ledger, RPC send methods,
or browser access. Observations are explicitly UNMATCHED and not merchant receipts.

Ankr Solana RPC may retain only ~16h of transaction history. A missed checkpoint
is an ERROR, never considered a complete scan. Run with a frequent systemd timer.
"""
from __future__ import annotations
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

RSTORY_MINT = 'RstyC4aoSD1JKPGTxnjB3PkWdRzV3yoePH1XiPMxBfz'
NETWORK_CHAINS = {'mainnet-beta': 'solana', 'devnet': 'solana_devnet'}
RPC_ALLOWED = frozenset({'getBalance','getTokenAccountsByOwner','getSignaturesForAddress','getTransaction'})
PUBKEY_ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
PUBKEY_RE=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
KEY_RE=re.compile(r'^[A-Za-z0-9_-]{8,256}$')
SIG_RE=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{80,96}$')
MAX_RESPONSE=2_000_000
MAX_HISTORY_PAGES=4
PAGE_LIMIT=100

class WatchError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')


def valid_pubkey(value):
    if type(value) is not str or not PUBKEY_RE.fullmatch(value):return False
    n=0
    for ch in value:n=n*58+PUBKEY_ALPHABET.index(ch)
    leading=len(value)-len(value.lstrip('1'))
    return len(b'\x00'*leading+n.to_bytes((n.bit_length()+7)//8,'big'))==32


def valid_signature(s):
    return type(s) is str and bool(SIG_RE.fullmatch(s))


def positive_integer(v, *, allow_zero=True):
    if type(v) is int and v >= (0 if allow_zero else 1):return v
    if type(v) is str and re.fullmatch(r'(0|[1-9][0-9]{0,30})',v):
        n=int(v)
        if n>0 or allow_zero:return n
    raise WatchError('Unrecognized balance or amount')


def amount_format(units, decimals):
    return format(Decimal(units)/(Decimal(10)**decimals),f'.{decimals}f')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


class AnkrRpc:
    def __init__(self,key,network='mainnet-beta',transport=None):
        if network not in NETWORK_CHAINS:
            raise WatchError('Unrecognized Solana network')
        if type(key) is not str or not KEY_RE.fullmatch(key):
            raise WatchError('Ankr RPC key missing or invalid')
        self.network=network
        self._url=f'https://rpc.ankr.com/{NETWORK_CHAINS[network]}/{key}'
        self._transport=transport

    def call(self,method,params):
        if method not in RPC_ALLOWED:raise WatchError('Unapproved read-only RPC method')
        payload={'jsonrpc':'2.0','id':1,'method':method,'params':params}
        if self._transport:
            obj=self._transport(method,params)
        else:
            req=Request(self._url,data=json.dumps(payload).encode(),
                method='POST',headers={'Content-Type':'application/json','Accept':'application/json',
                                       'User-Agent':'GnosisWatchOnly/1.0'})
            try:
                with build_opener(NoRedirect).open(req,timeout=12) as response:
                    if response.status != 200:raise WatchError('Ankr RPC returned unexpected status')
                    raw=response.read(MAX_RESPONSE+1)
                    if len(raw)>MAX_RESPONSE:raise WatchError('Ankr RPC response too large')
                obj=json.loads(raw)
            except (HTTPError,URLError,OSError,TimeoutError,ValueError) as exc:
                if isinstance(exc,WatchError):raise
                # RPC URLs contain API keys: NEVER print or attach the underlying exception.
                raise WatchError('Ankr RPC temporarily unavailable') from None
        if not isinstance(obj,dict) or obj.get('jsonrpc')!='2.0' or 'error' in obj or 'result' not in obj:
            raise WatchError('Ankr RPC returned an error or invalid response')
        return obj['result']


def configuration(db,env=None):
    env=os.environ if env is None else env
    if env.get('GNOSIS_SOLANA_WATCH_ENABLED') != 'YES':
        raise WatchError('Watch is disabled. Set GNOSIS_SOLANA_WATCH_ENABLED=YES after configuring your treasury')
    net=env.get('GNOSIS_SOLANA_WATCH_NETWORK','mainnet-beta')
    if net not in NETWORK_CHAINS:raise WatchError('Unrecognized network')
    # The existing Financials setting can be used without copying the wallet to env.
    saved=db.execute('SELECT solana_address,rstory_mint FROM gnosis_finance_settings WHERE singleton=1').fetchone()
    if not saved:raise WatchError('Financials wallet settings are missing')
    address=env.get('GNOSIS_SOLANA_WATCH_ADDRESS') or saved[0]
    if not valid_pubkey(address):raise WatchError('Configure a valid Solana treasury address in Financials first')
    mint=(env.get('GNOSIS_SOLANA_WATCH_DEVNET_MINT') if net=='devnet' else RSTORY_MINT)
    if not valid_pubkey(mint):raise WatchError('Valid devnet test mint required')
    if net=='mainnet-beta' and saved[1] and saved[1] != RSTORY_MINT:
        raise WatchError('Financials token mint does not match the pinned mainnet RSTORY mint')
    key=env.get('ANKR_API_KEY') or env.get('GNOSIS_ANKR_API_KEY')
    if not key or not KEY_RE.fullmatch(key):raise WatchError('Ankr RPC key missing')
    return net,address,mint,key


def account_keys(tx):
    try:
        xs=tx['transaction']['message']['accountKeys']
    except (KeyError,TypeError):raise WatchError('RPC transaction account keys missing') from None
    if not isinstance(xs,list):raise WatchError('RPC transaction account keys unavailable')
    out=[]
    for x in xs:
        s=x if isinstance(x,str) else x.get('pubkey') if isinstance(x,dict) else None
        if not valid_pubkey(s):raise WatchError('RPC transaction account key malformed')
        out.append(s)
    return out


def verified_delta(tx,target,asset,mint):
    """Calculate net **observed** inflow, NOT proof of an invoice payment.

    Token balances must refer to the specific SPL token account AND pinned mint.
    We do not infer senders, references, or transaction intent from balance changes.
    """
    if not isinstance(tx,dict) or not isinstance(tx.get('meta'),dict):
        raise WatchError('Transaction not available from RPC history')
    if tx['meta'].get('err') is not None:return 0
    keys=account_keys(tx)
    if target not in keys:raise WatchError('Watched target missing from transaction account keys')
    i=keys.index(target)
    meta=tx['meta']
    if asset=='SOL':
        pre=meta.get('preBalances');post=meta.get('postBalances')
        if not isinstance(pre,list) or not isinstance(post,list) or len(pre)!=len(keys) or len(post)!=len(keys):
            raise WatchError('Missing SOL balance information')
        return positive_integer(post[i])-positive_integer(pre[i])
    if asset!='RSTORY':raise WatchError('Unsupported watched asset')
    def matching(field):
        result=0
        rows=meta.get(field)
        if not isinstance(rows,list):raise WatchError('Missing SPL token balance information')
        matched=False
        for item in rows:
            if not isinstance(item,dict) or item.get('accountIndex') != i or item.get('mint') != mint:continue
            parsed=item.get('uiTokenAmount')
            if not isinstance(parsed,dict) or parsed.get('decimals')!=6:
                raise WatchError('RSTORY token precision mismatch')
            if matched:raise WatchError('Duplicate SPL balance entry')
            result=positive_integer(parsed.get('amount'))
            matched=True
        return result
    return matching('postTokenBalances')-matching('preTokenBalances')


def recent_signatures(rpc,target,marker,*,since_epoch=None,recovery_since_epoch=None):
    """Fetch all new finalized signatures to exact checkpoint or to startup time.

    We NEVER silently advance the cursor past an unscanned interval. RPC does
    not guarantee archival; a missing checkpoint is an error requiring review.
    """
    found=False;result=[];before=None;exhausted=False
    for _ in range(MAX_HISTORY_PAGES):
        opts={'limit':PAGE_LIMIT,'commitment':'finalized'}
        if before:opts['before']=before
        page=rpc.call('getSignaturesForAddress',[target,opts])
        if not isinstance(page,list):raise WatchError('RPC signature history malformed')
        for item in page:
            if not isinstance(item,dict) or not valid_signature(item.get('signature')):
                raise WatchError('Unrecognized transaction signature')
            sig=item['signature']
            if sig==marker:
                found=True;break
            if item.get('confirmationStatus') not in ('finalized',None):
                raise WatchError('RPC returned a non-finalized transaction')
            if since_epoch is not None or recovery_since_epoch is not None:
                block_time=item.get('blockTime')
                if type(block_time) is not int:
                    raise WatchError('Transaction time unavailable during backfill')
                cutoff = since_epoch if since_epoch is not None else recovery_since_epoch
                # When a long-dormant checkpoint has been pruned but polling
                # has remained continuous, re-read the entire recent window.
                # The transfer uniqueness constraint makes overlaps harmless.
                if block_time < cutoff:
                    found=True;break
            result.append(item)
        if found:break
        if len(page)<PAGE_LIMIT:
            exhausted=True;break
        before=page[-1]['signature']
    if marker and not found and recovery_since_epoch is None:
        raise WatchError('Watch checkpoint missing from Ankr history; manual archival reconciliation required')
    if since_epoch is not None and not found and not exhausted:
        raise WatchError('New account backfill too large; no checkpoint advanced')
    if marker is not None and not found and recovery_since_epoch is not None and not exhausted:
        raise WatchError('Watch recovery window exceeds RPC history page limit')
    if marker is None and since_epoch is None and len(result)>=PAGE_LIMIT:
        # Brand-new watcher should *bootstrap* without trying to replay past data.
        return result[:1]
    if marker is None and since_epoch is None:
        return result[:1]
    if not found and not exhausted:
        raise WatchError('Unbounded RPC history; no checkpoint advanced')
    return result


def _read_transfer(rpc,target,asset,mint,item,cache,network,wallet):
    if item.get('err') is not None:return None
    sig=item['signature']
    if sig not in cache:
        cache[sig]=rpc.call('getTransaction',[sig,{'encoding':'jsonParsed','commitment':'finalized',
                                                  'maxSupportedTransactionVersion':0}])
    tx=cache[sig]
    if tx is None:raise WatchError('Finalized transaction unavailable from RPC history')
    delta=verified_delta(tx,target,asset,mint)
    if delta<=0:return None
    bt=tx.get('blockTime');slot=tx.get('slot')
    if type(bt) is not int or type(slot) is not int or bt<=0 or slot<0:
        raise WatchError('Transaction lacks reliable block time or slot')
    return (network,wallet,sig,asset,target,slot,bt,str(delta),amount_format(delta,9 if asset=='SOL' else 6),utc_now())


def scan(db,rpc,env=None):
    net,wallet,mint,_=configuration(db,env)
    if rpc.network != net:raise WatchError('RPC network mismatch')
    observed_at=utc_now()
    # Read-only chain calls first; no DB transaction held open over the network.
    sol=rpc.call('getBalance',[wallet,{'commitment':'finalized'}])
    if not isinstance(sol,dict):raise WatchError('SOL balance unavailable')
    lamports=positive_integer(sol.get('value'))
    tokens=rpc.call('getTokenAccountsByOwner',[wallet,{'mint':mint},
                                               {'encoding':'jsonParsed','commitment':'finalized'}])
    if not isinstance(tokens,dict) or not isinstance(tokens.get('value'),list):
        raise WatchError('Token accounts unavailable')
    accounts=[];rst_total=0
    for item in tokens['value']:
        if not isinstance(item,dict) or not valid_pubkey(item.get('pubkey')):
            raise WatchError('Malformed token account')
        info=(((item.get('account') or {}).get('data') or {}).get('parsed') or {}).get('info')
        if not isinstance(info,dict) or info.get('mint')!=mint or info.get('owner')!=wallet:
            raise WatchError('Token-account owner or mint mismatch')
        node=info.get('tokenAmount')
        if not isinstance(node,dict) or node.get('decimals')!=6:
            raise WatchError('Token-account decimals mismatch')
        accounts.append(item['pubkey'])
        rst_total+=positive_integer(node.get('amount'))
    if len(accounts)>16 or len(accounts)!=len(set(accounts)):
        raise WatchError('Unexpected number of duplicate token accounts')
    targets=[(wallet,'SOL')]+[(a,'RSTORY') for a in accounts]
    cache={};plans=[];latest_base=db.execute('''SELECT started_at FROM gnosis_solana_watch_state
                    WHERE network=? AND wallet=? ORDER BY started_at LIMIT 1''',(net,wallet)).fetchone()
    # On first run, every target is baselined, no past transfers considered new.
    first_start_epoch=None
    if latest_base:
        first_start_epoch=int(datetime.fromisoformat(latest_base[0].replace('Z','+00:00')).timestamp())
    for addr,asset in targets:
        row=db.execute('SELECT newest_signature,started_at,last_scanned_at FROM gnosis_solana_watch_state WHERE network=? AND wallet=? AND target_address=?',
                       (net,wallet,addr)).fetchone()
        if row:
            # Empty initial history has no cursor. Backfill since the watch began
            # so the first incoming payment is never skipped.
            since=int(datetime.fromisoformat(row[1].replace('Z','+00:00')).timestamp()) if row[0] is None else None
            recovery=None
            if row[0] is not None and row[2]:
                last=int(datetime.fromisoformat(row[2].replace('Z','+00:00')).timestamp())
                if 0 <= datetime.now(timezone.utc).timestamp()-last < 900:
                    recovery=last-2
            new=recent_signatures(rpc,addr,row[0],since_epoch=since,recovery_since_epoch=recovery)
            newest=new[0]['signature'] if new else row[0]
            entries=[_read_transfer(rpc,addr,asset,mint,item,cache,net,wallet) for item in reversed(new)]
            plans.append((addr,asset,False,newest,[x for x in entries if x]))
        elif first_start_epoch is not None:
            new=recent_signatures(rpc,addr,None,since_epoch=first_start_epoch)
            newest=new[0]['signature'] if new else None
            entries=[_read_transfer(rpc,addr,asset,mint,item,cache,net,wallet) for item in reversed(new)]
            plans.append((addr,asset,True,newest,[x for x in entries if x]))
        else:
            # New watch: ignore historical transfers rather than label them payments.
            new=recent_signatures(rpc,addr,None)
            plans.append((addr,asset,True,new[0]['signature'] if new else None,[]))
    # All targets fully scanned: commit exactly once. No cursor advances on failure.
    db.execute('BEGIN IMMEDIATE')
    try:
        inserted=0
        for addr,asset,is_new,newest,entries in plans:
            if is_new:
                db.execute('''INSERT INTO gnosis_solana_watch_state
                (network,wallet,target_address,asset,started_at,newest_signature,last_scanned_at)
                VALUES(?,?,?,?,?,?,?)''',(net,wallet,addr,asset,observed_at,newest,observed_at))
            else:
                db.execute('''UPDATE gnosis_solana_watch_state
                SET newest_signature=?,last_scanned_at=?,last_error=NULL
                WHERE network=? AND wallet=? AND target_address=?''',
                (newest,observed_at,net,wallet,addr))
            for entry in entries:
                cur=db.execute('''INSERT OR IGNORE INTO gnosis_solana_watch_observations
                (network,wallet,signature,asset,destination_account,block_slot,block_time,delta_base_units,amount_display,detected_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',entry)
                inserted+=cur.rowcount
        db.execute('''INSERT INTO gnosis_solana_watch_snapshots
        (network,wallet,observed_at,sol_lamports,rstory_base_units,token_account_count)
        VALUES(?,?,?,?,?,?)''',
        (net,wallet,observed_at,str(lamports),str(rst_total),len(accounts)))
        db.commit()
        return {'network':net,'wallet':wallet,'sol':amount_format(lamports,9),
                'rstory':amount_format(rst_total,6),'token_accounts':len(accounts),
                'new_observations':inserted,'watch_targets':len(targets),
                'observed_at':observed_at,'payments_enabled':False,'credits_issued':0}
    except Exception:
        db.rollback()
        raise


def status(db):
    targets=db.execute('SELECT COUNT(*) FROM gnosis_solana_watch_state').fetchone()[0]
    n=db.execute('SELECT COUNT(*) FROM gnosis_solana_watch_observations').fetchone()[0]
    snap=db.execute('''SELECT network,wallet,observed_at,sol_lamports,rstory_base_units,token_account_count
                    FROM gnosis_solana_watch_snapshots ORDER BY observed_at DESC LIMIT 1''').fetchone()
    return {'targets':targets,'unmatched_observations':n,'last_snapshot':dict(snap) if snap else None,
            'payments_enabled':False,'credits_issued':0}
