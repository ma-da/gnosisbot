#!/usr/bin/env python3
"""Fail closed on unsafe production configuration, missing migrations or wrong GQTP key."""
import os, sys, sqlite3, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gnosis_platform.config import get_settings
from gnosis_platform import gqtp

def validate():
    s=get_settings()
    def require(x,msg):
        if not x:raise ValueError(msg)
    require(os.getenv('GNOSIS_WEB_ORIGIN')=='https://gnosis.bot','Production origin must exactly match HTTPS hostname')
    require(os.getenv('GNOSIS_PUBLIC_BASE_URL')=='https://gnosis.bot','Production public base URL mismatch')
    require(os.getenv('GNOSIS_ALLOW_INSECURE_COOKIE')!='1','Insecure cookies forbidden')
    require(s.data_dir==Path('/var/lib/gnosis') and s.db_path.is_relative_to(s.data_dir),'Private state location mismatch')
    require(s.db_path.is_file(),'Database missing: initialize or restore before startup')
    for k in ('GNOSIS_ENABLE_IBM_LIVE_SUBMISSION','GNOSIS_ENABLE_IBM_AUTO_SUBMIT','GNOSIS_ENABLE_IBM_PILOT','GNOSIS_ENABLE_IBM_ADMIN_TRIAL','GNOSIS_ENABLE_TRIAL_EMAIL','GNOSIS_PROVISION_ADMIN'):
        require(os.getenv(k)!='YES',k+' must be disabled in this alpha service')
    require(os.getenv('GNOSIS_ENABLE_CONSULTATION_SANDBOX')!='1','Sandbox disabled in production')
    if os.getenv('GNOSIS_ENABLE_QCI')=='1':require(bool(os.getenv('QCI_API_TOKEN')),'QCI credential missing')
    if any(os.getenv(k)=='YES' for k in ('GNOSIS_ENABLE_EMAIL_VERIFICATION','GNOSIS_ENABLE_COMPLETION_EMAIL')):
        from cryptography.fernet import Fernet
        require(all(os.getenv(k) for k in ('GNOSIS_CONTACT_ENCRYPTION_KEY','RESEND_API_KEY','GNOSIS_RESEND_FROM')),'Mail configuration incomplete')
        try:Fernet(os.environ['GNOSIS_CONTACT_ENCRYPTION_KEY'].encode())
        except Exception:raise ValueError('Invalid contact encryption key format') from None
    with sqlite3.connect(s.db_path.as_uri()+'?mode=ro',uri=True) as db:
        expected={p.name for p in (ROOT/'gnosis_platform/migrations').glob('*.sql')}
        applied={r[0] for r in db.execute('SELECT version FROM schema_migrations')}
        require(applied==expected,'Migration set differs; run explicit migration before start')
        latest=db.execute('SELECT envelope_json FROM gqtp_checkpoints ORDER BY tree_size DESC LIMIT 1').fetchone()
        if latest:
            envelope=json.loads(latest[0]);key=gqtp.read_key(s.data_dir/'transparency/signing.key')
            require(gqtp.verify_checkpoint(envelope,gqtp.public_key(key)),'Existing checkpoint/signing identity mismatch')
        if os.getenv('GNOSIS_ENABLE_IBM_PAST')=='1' or os.getenv('GNOSIS_ENABLE_RUNE_PAST')=='1':
            require(db.execute("SELECT value FROM gqtp_settings WHERE key='inventory_enforced'").fetchone()==('1',),'Past requires GQTP enforcement')
            require(latest is not None,'Past requires existing signed checkpoint')
    print('Production configuration and migration guard: PASS')
if __name__=='__main__':
    try:validate()
    except (OSError,ValueError,sqlite3.Error,KeyError) as exc:
        print('Production startup refused: '+str(exc),file=sys.stderr);sys.exit(1)
