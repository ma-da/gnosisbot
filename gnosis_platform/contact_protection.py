"""First-party contact admission; no IP, browser or message fingerprints."""
import hashlib, hmac, os, re, secrets, time
from datetime import datetime, timedelta, timezone
from .account_email import stamp

BODY_LIMIT = 8192

def setting(name, default, low, high):
    try: value = int(os.getenv('GNOSIS_CONTACT_' + name, str(default)))
    except ValueError: raise RuntimeError('Invalid contact protection setting: ' + name) from None
    if not low <= value <= high:
        raise RuntimeError('Invalid contact protection setting: ' + name)
    return value

def policy():
    minimum = setting('MIN_SECONDS',16,16,300)
    ttl = setting('TOKEN_TTL_SECONDS',3600,301,86400)
    return minimum, ttl, setting('EMAIL_PER_DAY',3,1,1000), setting('GLOBAL_PER_HOUR',60,1,10000), setting('QUARANTINE_DAYS',14,1,90)

def now_ms(): return time.time_ns() // 1_000_000

def signature(value):
    key = os.environ.get('GNOSIS_CONTACT_ENCRYPTION_KEY')
    if not key: raise RuntimeError('Contact key missing')
    return hmac.new(key.encode(), b'gnosis-contact-token-v1\0'+value.encode('ascii'), hashlib.sha256).hexdigest()

def issue():
    minimum,ttl,*_ = policy()
    now=now_ms()
    value=f'{now}.{now+ttl*1000}.{secrets.token_hex(24)}'
    return {'token':value+'.'+signature(value),'minimum_seconds':minimum,'expires_in':ttl}

class AdmissionError(Exception):
    def __init__(self,status,code,wait=None):
        self.status,self.code,self.wait=status,code,wait
        super().__init__(code)

def verify(token,now):
    if not isinstance(token,str) or not re.fullmatch(r'[0-9]{13}\.[0-9]{13}\.[0-9a-f]{48}\.[0-9a-f]{64}',token):
        raise AdmissionError(403,'token_invalid')
    value,mac=token.rsplit('.',1)
    if not hmac.compare_digest(signature(value),mac): raise AdmissionError(403,'token_invalid')
    issued,expires,nonce=value.split('.')
    issued,expires=int(issued),int(expires)
    if now < issued or now >= expires or not 0 < expires-issued <= 86400000:
        raise AdmissionError(403,'token_expired')
    wait=policy()[0]*1000-(now-issued)
    if wait>0: raise AdmissionError(425,'too_early',(wait+999)//1000)
    return nonce,expires

def record(db,outcome,now=None):
    minute=(now_ms() if now is None else now)//60000
    db.execute('DELETE FROM gnosis_contact_spam_counters WHERE minute<?',(minute-1440,))
    db.execute('''INSERT INTO gnosis_contact_spam_counters(minute,outcome,n) VALUES(?,?,1)
      ON CONFLICT(minute,outcome) DO UPDATE SET n=n+1''',(minute,outcome))

def statistics(db):
    minute=now_ms()//60000
    result=dict.fromkeys(('accepted','quarantined','rejected','rate_limited'),0)
    for row in db.execute('SELECT outcome,sum(n) FROM gnosis_contact_spam_counters WHERE minute>? GROUP BY outcome',(minute-1440,)):
        result[row[0]]=row[1]
    return result

def prune(db,now=None):
    now=now_ms() if now is None else now
    cutoff=stamp(datetime.fromtimestamp(now/1000,timezone.utc)-timedelta(days=policy()[4]))
    at=stamp(datetime.fromtimestamp(now/1000,timezone.utc))
    # Preserve pseudonymous row IDs and existing audit/FK links, as in manual deletion.
    changed=db.execute('''UPDATE gnosis_site_contact_messages
      SET name_ciphertext=X'',email_ciphertext=X'',message_ciphertext=X'',
      email_digest=lower(hex(randomblob(32))),deleted_at=?,read_at=COALESCE(read_at,?),
      archived_at=COALESCE(archived_at,?),quarantine_reason=NULL
      WHERE deleted_at IS NULL AND quarantine_reason IS NOT NULL AND created_at<=?''',(at,at,at,cutoff)).rowcount
    db.execute('DELETE FROM gnosis_contact_consumed_tokens WHERE accepted_ms<? AND expires_ms<=?',(now-86400000,now))
    db.execute('DELETE FROM gnosis_contact_spam_counters WHERE minute<?',(now//60000-1440,))
    return changed

def quarantine_reason(message):
    links=len(re.findall(r'(?i)(?:https?://|www\.)[^\s<>]+',message))
    promo=bool(re.search(r'(?i)\b(?:backlinks?|guest posts?|seo services|link building|domain authority|buy traffic)\b',message))
    pitch=bool(re.search(r'(?i)\b(?:offer|pricing|packages?|discount|purchase|guaranteed|services|sell|buy)\b',message))
    if links>=3: return 'multiple_links'
    if promo and (links or pitch): return 'promotional_pattern'
    return None
