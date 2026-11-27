"""Server-owned rune policies and configuration; no hardware admission yet."""
import os
APP_ID='runes'
SCHEMA='rune-reading-v0'
MODES=('pouch','sticks')
SOURCES={'classic':(0,0,60,'server_crypto',False), 'qrng_private':(0,1,60,'qci',False),
         'qrng_public':(0,1,60,'nist',False), 'quantum_past':(5,0,60,'ibm_inventory',False),
         'quantum_future':(10,0,60,'ibm_runtime',True)}

def policies(cls):
    return {f'runes.{m}.{s}':cls(f'runes.{m}.{s}',cost,minbal,cooldown,async_job,provider)
            for m in MODES for s,(cost,minbal,cooldown,provider,async_job) in SOURCES.items()}

def spec(service_id):
    _,mode,source=service_id.split('.')
    if mode not in MODES or source not in SOURCES: raise ValueError('Unknown rune service')
    return mode,source,SOURCES[source][3]

def availability(service_id, connect_db=None):
    mode,source,provider=spec(service_id)
    if provider=='ibm_runtime': return False,'rune_hardware_not_qualified'
    if provider=='ibm_inventory':
        if os.environ.get('GNOSIS_ENABLE_RUNES')!='1' or os.environ.get('GNOSIS_ENABLE_RUNE_PAST')!='1': return False,'rune_hardware_not_qualified'
        from contextlib import closing
        from .db import connect
        from .rune_past_inventory import available_count
        try:
            with closing((connect_db or connect)()) as db:
                ready=available_count(db,mode)>0
        except Exception: ready=False
        return ready, 'ibm_past_approved_inventory' if ready else 'rune_inventory_unavailable'
    if os.environ.get('GNOSIS_ENABLE_RUNES')!='1': return False,'runes_disabled'
    if source=='classic': return True,'server_crypto'
    if source=='qrng_private' and os.environ.get('GNOSIS_ENABLE_QCI')=='1' and os.environ.get('QCI_API_TOKEN'):
        return True,'qci_live'
    if source=='qrng_public' and os.environ.get('GNOSIS_ENABLE_NIST')=='1' and os.environ.get('GNOSIS_ENABLE_RUNE_NIST')=='1':
        return True,'nist_beacon_v2_enabled'
    return False,'provider_not_connected'

def catalog_entry(p, connect_db=None):
    available,label=availability(p.service_id,connect_db)
    mode,source,_=spec(p.service_id)
    return dict(service_id=p.service_id,application_id=APP_ID,mode=mode,credits=p.credits,
                min_balance=p.min_balance,cooldown_seconds=p.cooldown_seconds,async_job=p.async_job,
                provider=p.provider,fallback_active=False,available=available,availability=label,
                price_provisional=(source == 'quantum_future'))
