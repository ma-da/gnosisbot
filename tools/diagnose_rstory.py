"""Read-only price feed diagnostic; makes no quote, payment or credit entries."""
import sys
from contextlib import closing
from datetime import datetime,timezone
try:
    from gnosis_platform import commerce_price_stage as price
    from gnosis_platform.db import connect
    pool_id=price.RSTORY_POOL_ID
    print('policy:',price.POLICY)
    for kind,url in (
        ('pool',price.POOL_BASE+pool_id),
        ('raydium_mint',price.RAYDIUM_MINT_PRICE_URL),
        ('trades',price.GECKO_TRADES_BASE+pool_id+price.GECKO_TRADES_URL_SUFFIX)
    ):
        try:
            result=price._fetch_json(url)
            if kind=='pool':
                meta=price.parse_raydium_pool(result,pool_id)
                print(kind,'OK','tvl',meta['tvl'],'reserve',meta['reserve'])
            elif kind=='raydium_mint':
                print(kind,'USD price:',price.raydium_market_price(result))
            else:
                trade=price.parse_last_trades(result,pool_id,datetime.now(timezone.utc))
                print(kind,'latest qualifying trade:',
                      {k:trade[k] for k in ('price_usd','timestamp','signature')} if trade else None)
        except price.PricingError as ex:
            print(kind,'FAILED',str(ex))
    with closing(connect()) as db:
        if hasattr(price,'cached_last_trade'):
            trade=price.cached_last_trade(db,pool_id,datetime.now(timezone.utc))
            print('cached verified trade:',
                  {k:trade[k] for k in ('price_usd','timestamp','signature')} if trade else None)
except Exception as ex:
    # Do not include secret-bearing URLs or credentials in diagnostic output.
    print('DIAGNOSTIC FAILED:',type(ex).__name__,str(ex)[:160])
    sys.exit(1)
