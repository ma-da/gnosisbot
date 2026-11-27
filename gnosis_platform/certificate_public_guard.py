"""Bound public verification work and redact share bearer URLs from Uvicorn access logs.
Proxy/CDN logging policy is separate; this does not change Caddy configuration.
"""
import logging,re,time,threading
from collections import OrderedDict,deque
from starlette.responses import PlainTextResponse

_PATTERN=re.compile(r'(/api/v1/c/)[^\s/?]+')
class ShareLogFilter(logging.Filter):
    def filter(self,record):
        if isinstance(record.args,tuple):
            record.args=tuple(_PATTERN.sub(r'\1[redacted]',v) if isinstance(v,str) else v for v in record.args)
        if isinstance(record.msg,str):record.msg=_PATTERN.sub(r'\1[redacted]',record.msg)
        return True

def install_access_log_filter():
    logger=logging.getLogger('uvicorn.access')
    if not any(isinstance(f,ShareLogFilter) for f in logger.filters):logger.addFilter(ShareLogFilter())

class PublicCertificateGuard:
    def __init__(self,app,per_client=30,total=120):
        self.app=app;self.per_client=per_client;self.total=total
        self.lock=threading.Lock();self.clients=OrderedDict();self.global_hits=deque()
    def allow(self,client):
        now=time.monotonic();cutoff=now-60
        with self.lock:
            while self.global_hits and self.global_hits[0]<=cutoff:self.global_hits.popleft()
            if len(self.global_hits)>=self.total:return False
            if client not in self.clients:
                # Bounded memory; global limit remains authoritative even with rotating IPs.
                if len(self.clients)>=2048:self.clients.popitem(last=False)
                self.clients[client]=deque()
            hits=self.clients[client];self.clients.move_to_end(client)
            while hits and hits[0]<=cutoff:hits.popleft()
            if len(hits)>=self.per_client:return False
            hits.append(now);self.global_hits.append(now);return True
    async def __call__(self,scope,receive,send):
        if scope['type']=='http' and scope.get('path','').startswith('/api/v1/c/'):
            client=(scope.get('client') or ('unknown',0))[0]
            if not self.allow(client):
                await PlainTextResponse('Certificate verification rate limit reached.',status_code=429,headers={'Retry-After':'60','Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})(scope,receive,send);return
        await self.app(scope,receive,send)
