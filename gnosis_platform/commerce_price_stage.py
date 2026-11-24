"""Read-only market-derived *staging* preview prices, never payment instructions.

Only explicitly invoked from an authenticated admin's POST /quote when an operator
has configured an indicative pack USD price. No wallet addresses, signers, custody,
issuance, settlement, or blockchain transfer interfaces.
"""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

RSTORY_MINT = 'RstyC4aoSD1JKPGTxnjB3PkWdRzV3yoePH1XiPMxBfz'
# Observed Raydium CPMM RSTORY/WSOL market; validated against returned mint.
RSTORY_POOL_ID = 'HvAbcRysAgYaiFfESyL8ZKt5t4Yk7YX9pZCiehp7d9Ad'
POOL_BASE = 'https://api-v3.raydium.io/pools/info/ids?ids='
RAYDIUM_MINT_PRICE_URL = 'https://api-v3.raydium.io/mint/price?mints=' + RSTORY_MINT
GECKO_TRADES_BASE = 'https://api.geckoterminal.com/api/v2/networks/solana/pools/'
# An independently indexed swap record; Raydium API v3 does not publish swap history.
GECKO_TRADES_URL_SUFFIX = '/trades'
GECKO_CANDLE_SUFFIX = '/ohlcv/minute?aggregate=1&limit=1&currency=usd&token=' + RSTORY_MINT
LAST_TRADE_MIN_USD = Decimal('1')
SOL_PRICE_URL = ('https://api.coingecko.com/api/v3/simple/price?'
                 'ids=solana&vs_currencies=usd&include_last_updated_at=true')
POLICY = 'raydium-market-price-80-percent-v2'
SOL_POLICY = 'coingecko-sol-usd-no-discount-v1'
STRIPE_POLICY = 'usd-face-value-staging-v1'
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
MINT_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
MAX_RESPONSE = 65536
TIMEOUT_SECONDS = 6
MAX_SOL_PRICE_AGE_SECONDS = 300

class PricingError(ValueError):
    pass


def decimal(value, *, name, max_value=None):
    if isinstance(value, bool) or value is None or isinstance(value, (list, dict)):
        raise PricingError(f'Invalid {name} from price feed')
    if isinstance(value, float) and not (value > 0 and value < float('inf')):
        raise PricingError(f'Invalid {name} from price feed')
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise PricingError(f'Invalid {name} from price feed') from None
    if not parsed.is_finite() or parsed <= 0 or (max_value is not None and parsed > max_value):
        raise PricingError(f'Invalid {name} from price feed')
    return parsed


def pack_usd(raw):
    if type(raw) is not str or not re.fullmatch(r'(?:[1-9]\d{0,3}|0)\.\d{2}', raw.strip()):
        raise PricingError('Pack USD price must be a positive dollar amount with two decimals')
    amount = decimal(raw.strip(), name='pack USD price', max_value=Decimal('9999.99'))
    if amount < Decimal('0.01'):
        raise PricingError('Pack USD price must be at least $0.01')
    return amount


def valid_pubkey(value):
    if type(value) is not str or not MINT_RE.fullmatch(value):
        return False
    n = 0
    for c in value:
        n = n * 58 + ALPHABET.index(c)
    leading = len(value) - len(value.lstrip('1'))
    try:
        decoded = b'\0' * leading + n.to_bytes((n.bit_length() + 7)//8, 'big')
    except OverflowError:
        return False
    return len(decoded) == 32


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_json(url):
    """Fixed-host HTTPS GET, bounded response, no redirects, sanitized failures."""
    if not (url in (SOL_PRICE_URL, RAYDIUM_MINT_PRICE_URL) or
            (url.startswith(POOL_BASE) and valid_pubkey(url[len(POOL_BASE):])) or
            (url.startswith(GECKO_TRADES_BASE) and url.endswith(GECKO_TRADES_URL_SUFFIX) and
             valid_pubkey(url[len(GECKO_TRADES_BASE):-len(GECKO_TRADES_URL_SUFFIX)])) or
            (url.startswith(GECKO_TRADES_BASE) and url.endswith(GECKO_CANDLE_SUFFIX) and
             valid_pubkey(url[len(GECKO_TRADES_BASE):-len(GECKO_CANDLE_SUFFIX)]))):
        raise PricingError('Unapproved pricing source')
    req = Request(url, headers={'Accept':'application/json', 'User-Agent':'Gnosis-Staging-Price/3.0'}, method='GET')
    try:
        with build_opener(NoRedirect).open(req, timeout=TIMEOUT_SECONDS) as r:
            if r.status != 200:
                raise PricingError('Market data source unavailable')
            body = r.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise PricingError('Market data response exceeds size limit')
    except (HTTPError, URLError, TimeoutError, OSError):
        raise PricingError('Market data source unavailable; no quote created') from None
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeError):
        raise PricingError('Unrecognized market data response') from None
    if not isinstance(obj, dict):
        raise PricingError('Unrecognized market data response')
    return obj


def iso_utc(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def qty_rounded_up(amount, decimals):
    return amount.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_CEILING)


def fixed(x, digits):
    return format(x, f'.{digits}f')


def sol_quote(usd, *, now, fetch_json):
    obj = fetch_json(SOL_PRICE_URL)
    node = obj.get('solana')
    if not isinstance(node, dict):
        raise PricingError('SOL USD price unavailable')
    price = decimal(node.get('usd'), name='SOL USD reference', max_value=Decimal('1000000'))
    stamp = node.get('last_updated_at')
    if type(stamp) is not int or stamp <= 0:
        raise PricingError('SOL price update timestamp unavailable')
    age = now.timestamp() - stamp
    if age < -60 or age > MAX_SOL_PRICE_AGE_SECONDS:
        raise PricingError('SOL price reference is stale; no quote created')
    qty = qty_rounded_up(usd/price, 9)
    return {
        'policy': SOL_POLICY, 'asset':'SOL', 'usd_face_value':fixed(usd,2),
        'usd_payable_reference':fixed(usd,2),'asset_unit_price_usd':str(price),
        'asset_amount':fixed(qty,9), 'discount_bps':0,
        'price_source':'coingecko-sol-usd', 'source_url':SOL_PRICE_URL,
        'source_timestamp':datetime.fromtimestamp(stamp,timezone.utc).isoformat().replace('+00:00','Z'),
        'fetched_at':iso_utc(now), 'network':'solana-mainnet-beta',
        'note':'Staging preview only. This is not an instruction to send SOL.'
    }


def parse_raydium_pool(obj, pool_id):
    if obj.get('success') is not True or not isinstance(obj.get('data'), list) or len(obj['data']) != 1:
        raise PricingError('Exact Raydium pool unavailable')
    pool = obj['data'][0]
    if not isinstance(pool, dict) or pool.get('id') != pool_id or pool.get('type') != 'Standard':
        raise PricingError('Unrecognized pool identity or type')
    side = None
    for item in ('A','B'):
        mint = pool.get('mint'+item)
        if not isinstance(mint, dict) or type(mint.get('address')) is not str:
            raise PricingError('Pool mint details unavailable')
        if mint['address'] == RSTORY_MINT:
            if side is not None or mint.get('decimals') != 6:
                raise PricingError('RSTORY mint precision mismatch')
            side=item
    if side is None:
        raise PricingError('Configured pool does not contain the pinned RSTORY mint')
    partner = pool['mint' + ('B' if side=='A' else 'A')]['address']
    if not valid_pubkey(partner) or partner == RSTORY_MINT:
        raise PricingError('Pool counterasset mint is invalid')
    tvl = decimal(pool.get('tvl'), name='Raydium USD TVL', max_value=Decimal('1000000000000'))
    reserve = decimal(pool.get('mintAmount'+side), name='RSTORY pool reserve', max_value=Decimal('100000000000000000'))
    return {'tvl':tvl,'reserve':reserve,'partner_mint':partner,'pool_type':pool['type']}


def raydium_market_price(obj):
    """Official Raydium v3 mint/USD feed, never estimate from TVL."""
    if not isinstance(obj, dict) or obj.get('success') is not True:
        return None
    prices = obj.get('data')
    if not isinstance(prices, dict):
        return None
    raw = prices.get(RSTORY_MINT)
    try:
        return decimal(raw, name='Raydium RSTORY price', max_value=Decimal('1000000'))
    except PricingError:
        return None


def _date(raw):
    if type(raw) is not str:
        raise PricingError('Invalid swap time')
    try:
        parsed = datetime.fromisoformat(raw.replace('Z','+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timezone required')
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise PricingError('Invalid swap time') from None


def _signature(raw):
    return type(raw) is str and bool(re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{80,96}',raw))


def validate_last_trade(trade, pool_id, now):
    """Trust neither the latest array position nor untyped indexer data."""
    if not isinstance(trade, dict) or trade.get('pool_id') != pool_id or trade.get('mint') != RSTORY_MINT:
        return None
    if not _signature(trade.get('signature')):
        return None
    try:
        when = _date(trade.get('timestamp'))
        price = decimal(trade.get('price_usd'), name='swap USD price', max_value=Decimal('1000000'))
        volume = decimal(trade.get('volume_usd'), name='swap USD volume')
    except PricingError:
        return None
    if when > now or volume < LAST_TRADE_MIN_USD:
        return None
    return { 'mint':RSTORY_MINT, 'pool_id':pool_id,
             'signature':trade['signature'], 'timestamp':iso_utc(when),
             'price_usd':str(price), 'volume_usd':str(volume) }


def parse_last_trades(obj, pool_id, now):
    """Parse actual indexed swaps for the *pinned* Raydium CPMM pool.

    GeckoTerminal trades have from/to token addresses; use the RSTORY side's
    USD price regardless of swap direction. Skip anomalous, bogus, and
    non-token trades. Never treat pool-spot/cached quote as a last *sale*.
    """
    rows = obj.get('data') if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        return None
    valid = []
    for row in rows[:300]:
        if not isinstance(row, dict):
            continue
        attrs = row.get('attributes')
        if not isinstance(attrs, dict) or attrs.get('is_anomalous') is True:
            continue
        from_token = attrs.get('from_token_address')
        to_token = attrs.get('to_token_address')
        if from_token == RSTORY_MINT and to_token != RSTORY_MINT:
            price = attrs.get('price_from_in_usd')
        elif to_token == RSTORY_MINT and from_token != RSTORY_MINT:
            price = attrs.get('price_to_in_usd')
        else:
            continue
        candidate = validate_last_trade({
            'pool_id':pool_id,'mint':RSTORY_MINT,'signature':attrs.get('tx_hash'),
            'timestamp':attrs.get('block_timestamp'),'price_usd':price,
            'volume_usd':attrs.get('volume_in_usd')
        },pool_id,now)
        if candidate is not None:
            valid.append(candidate)
    return max(valid, key=lambda t:(t['timestamp'],t['signature'])) if valid else None


def validate_last_candle(candle, pool_id, now):
    """Most recent nonempty 1-minute close, a transparent last-trade proxy.

    A candle's close is *not* proof of a specific transaction signature or
    execution second. We never label this as a verified signed swap.
    """
    if not isinstance(candle, dict) or candle.get('pool_id') != pool_id or candle.get('mint') != RSTORY_MINT:
        return None
    try:
        stamp = candle.get('timestamp_epoch')
        if type(stamp) is not int or stamp <= 0 or stamp > now.timestamp()+60:
            return None
        price=decimal(candle.get('price_usd'),name='minute close USD price',max_value=Decimal('1000000'))
        volume=decimal(candle.get('volume'),name='minute candle volume')
    except PricingError:
        return None
    if volume<=0:return None
    return {'pool_id':pool_id,'mint':RSTORY_MINT,'timestamp_epoch':stamp,
            'timestamp':iso_utc(datetime.fromtimestamp(stamp,timezone.utc)),
            'price_usd':str(price),'volume':str(volume)}


def parse_last_candle(obj,pool_id,now):
    """GeckoTerminal OHLCV response: [unixminute, open, high, low, close, volume]."""
    try:
        rows=obj['data']['attributes']['ohlcv_list']
    except (KeyError,TypeError):return None
    if not isinstance(rows,list):return None
    valid=[]
    for row in rows[:10]:
        if not isinstance(row,list) or len(row)!=6:continue
        candidate=validate_last_candle({
            'pool_id':pool_id,'mint':RSTORY_MINT,
            'timestamp_epoch':row[0], 'price_usd':row[4], 'volume':row[5],
        },pool_id,now)
        if candidate:valid.append(candidate)
    return max(valid,key=lambda t:t['timestamp_epoch']) if valid else None


def cached_last_candle(db,pool_id,now):
    if db is None:return None
    try:
        rows=db.execute("""SELECT quote_snapshot_json FROM gnosis_commerce_price_snapshots
            WHERE asset='RSTORY' AND valuation_policy=? ORDER BY fetched_at DESC LIMIT 250""",(POLICY,)).fetchall()
    except Exception:return None
    valid=[]
    for row in rows:
        try:
            snap=json.loads(row['quote_snapshot_json'] if hasattr(row,'keys') else row[0])
            c=validate_last_candle(snap.get('last_candle'),pool_id,now)
            if c:valid.append(c)
        except (ValueError,TypeError,KeyError):continue
    return max(valid,key=lambda t:t['timestamp_epoch']) if valid else None


def cached_last_trade(db, pool_id, now):
    """Only reuse an earlier *verified swap*, never a TVL/spot quote.

    This leverages the existing 9007 snapshot JSON; no new migration needed.
    Read-only DB query, and guarded against malformed or legacy rows.
    """
    if db is None:
        return None
    try:
        rows = db.execute("""SELECT quote_snapshot_json
           FROM gnosis_commerce_price_snapshots
           WHERE asset='RSTORY' AND valuation_policy=?
           ORDER BY fetched_at DESC LIMIT 250""", (POLICY,)).fetchall()
    except Exception:
        return None
    valid = []
    for row in rows:
        try:
            snap = json.loads(row['quote_snapshot_json'] if hasattr(row,'keys') else row[0])
            candidate = validate_last_trade(snap.get('last_trade'),pool_id,now)
            if candidate is not None:
                valid.append(candidate)
        except (TypeError,ValueError,KeyError):
            continue
    return max(valid,key=lambda t:(t['timestamp'],t['signature'])) if valid else None


def rstory_quote(usd, *, now, pool_id, fetch_json, db=None):
    if not valid_pubkey(pool_id):
        raise PricingError('RSTORY Raydium pool ID is not configured or invalid')
    # Pin the *actual market*, even though token-level Raydium feed is USD.
    result = parse_raydium_pool(fetch_json(POOL_BASE + pool_id), pool_id)
    feed_price = None
    try:
        feed_price = raydium_market_price(fetch_json(RAYDIUM_MINT_PRICE_URL))
    except PricingError:
        pass

    last_trade = None
    try:
        last_trade = parse_last_trades(fetch_json(GECKO_TRADES_BASE + pool_id + GECKO_TRADES_URL_SUFFIX),pool_id,now)
    except PricingError:
        pass
    prior = cached_last_trade(db,pool_id,now)
    if prior is not None and (last_trade is None or prior['timestamp'] > last_trade['timestamp']):
        last_trade = prior

    last_candle=None
    if feed_price is None and last_trade is None:
        url=GECKO_TRADES_BASE+pool_id+GECKO_CANDLE_SUFFIX
        try:
            last_candle=parse_last_candle(fetch_json(url),pool_id,now)
        except PricingError:
            pass
        prior_candle=cached_last_candle(db,pool_id,now)
        if prior_candle and (last_candle is None or prior_candle['timestamp_epoch']>last_candle['timestamp_epoch']):
            last_candle=prior_candle

    if feed_price is not None:
        policy_price = feed_price
        source = 'raydium-mint-usd-feed'
        source_url = RAYDIUM_MINT_PRICE_URL
        source_ts = None  # Provider does not supply a reliable observed_at in this endpoint.
        note = ('Raydium published RSTORY/USD price. The 20% discount applies to the USD pack. '
                'Feed observation time not published; snapshot fetch time is recorded. Staging only; do not send tokens.')
    elif last_trade is not None:
        policy_price = decimal(last_trade['price_usd'], name='recorded trade USD price')
        source = 'verified-last-pool-swap'
        source_url = GECKO_TRADES_BASE + pool_id + GECKO_TRADES_URL_SUFFIX
        source_ts = last_trade['timestamp']
        note = ('No Raydium published RSTORY/USD feed price. Using the last identifiable pool swap '
                f"at {last_trade['timestamp']} UTC, not a current market quote. "
                '20% pack discount; staging only, do not send tokens.')
    elif last_candle is not None:
        policy_price=decimal(last_candle['price_usd'],name='indexed minute close price')
        source='indexed-last-traded-minute-close'
        source_url=GECKO_TRADES_BASE+pool_id+GECKO_CANDLE_SUFFIX
        source_ts=last_candle['timestamp']
        note=('No current Raydium price or transaction-level trade record. Using the last nonempty '
              f"indexed 1-minute market candle close at {last_candle['timestamp']} UTC. "
              'This is an approximate last-trade price, not a verified individual swap. '
              '20% pack discount; staging only. Do not send tokens.')
    else:
        raise PricingError('No RSTORY feed, qualifying trade, or indexed last-traded candle available; no quote created')
    discounted = usd * Decimal('0.80')
    qty = qty_rounded_up(discounted/policy_price,0)
    if qty <= 0:
        raise PricingError('RSTORY token quantity is invalid')
    return {
        'policy':POLICY,'asset':'RSTORY','mint':RSTORY_MINT,
        'usd_face_value':fixed(usd,2),'usd_payable_reference':fixed(discounted,2),
        'asset_unit_price_usd':str(policy_price),'asset_amount':fixed(qty,0),
        'quantity_rounding':'ceil-whole-rstory',
        'discount_bps':2000,'price_source':source,'source_url':source_url,
        'pool_id':pool_id,'pool_tvl_usd':str(result['tvl']),
        'pool_rst_reserve':str(result['reserve']),
        'pool_spot_equivalent_usd':None,'independent_tax_fmv_usd':None,
        'pool_pair_mint':result['partner_mint'],'pool_type':result['pool_type'],
        'last_trade':last_trade,'last_candle':last_candle,'source_timestamp':source_ts,
        'fetched_at':iso_utc(now),'network':'solana-mainnet-beta',
        'note':note
    }

def preview_pricing(method, usd_price, environment, *, now=None, fetch_json=None, db=None):
    """Price an operator-approved staging pack without creating a payment.

    Failure is closed: if requested pricing source fails, no quote should be saved.
    """
    usd=pack_usd(usd_price)
    now=now or datetime.now(timezone.utc)
    fetch_json=fetch_json or _fetch_json
    if method == 'stripe':
        return {
            'policy':STRIPE_POLICY,'asset':'USD','asset_amount':fixed(usd,2),
            'usd_face_value':fixed(usd,2),'usd_payable_reference':fixed(usd,2),
            'asset_unit_price_usd':'1','discount_bps':0,'price_source':'configured-usd-face',
            'source_timestamp':None,'fetched_at':iso_utc(now),
            'note':'Staging preview only. No Stripe checkout is created.'
        }
    if method == 'solana':
        return sol_quote(usd,now=now,fetch_json=fetch_json)
    if method == 'rstory':
        return rstory_quote(usd,now=now,pool_id=environment.get('GNOSIS_COMMERCE_RSTORY_POOL_ID') or RSTORY_POOL_ID,fetch_json=fetch_json,db=db)
    raise PricingError('Unsupported payment method')


def quote_labels(pricing):
    asset = pricing['asset']
    amount = pricing['asset_amount']
    face = pricing['usd_face_value']
    payable = pricing['usd_payable_reference']
    if asset == 'USD':
        amount_display = f'${amount} USD'
        context = 'USD pack price'
    elif asset == 'SOL':
        amount_display = f'{amount} SOL'
        context = f'${face} USD pack at current SOL/USD price'
    else:
        amount_display = f'{int(amount):,} RSTORY'
        context = f'20% off ${face} pack; ${payable} basis'
    return (
        f'STAGING ONLY — NO CHARGE | Illustrative: {amount_display} ({context})',
        'No payment or blockchain transaction will occur. Live network fees not included.',
        pricing['note']
    )
