"""Versioned service catalog. Values are server authoritative.

Billing and cooldown exemptions must be checked through server-side account roles,
never user-supplied fields. Local Classic operation is outside server cooldown.
"""
from dataclasses import dataclass
from types import MappingProxyType

@dataclass(frozen=True)
class ServicePolicy:
    service_id: str
    credits: int
    min_balance: int = 0
    cooldown_seconds: int = 60
    async_job: bool = False
    provider: str = ""
    fallback: str | None = None

_POLICIES = {
    "iching.classic": ServicePolicy("iching.classic", 0, cooldown_seconds=0, provider="browser_crypto"),
    "iching.qrng_private": ServicePolicy("iching.qrng_private", 0, min_balance=1, provider="qci", fallback="anu"),
    "iching.qrng_public": ServicePolicy("iching.qrng_public", 0, min_balance=1, provider="nist"),
    "iching.quantum_past": ServicePolicy("iching.quantum_past", 5, provider="ibm_inventory"),
    "iching.quantum_future": ServicePolicy("iching.quantum_future", 10, async_job=True, provider="ibm_runtime"),
    "iching.ai_enhancement": ServicePolicy("iching.ai_enhancement", 1, cooldown_seconds=0, provider="deepinfra"),
}
from .rune_services import policies as rune_policies
_POLICIES.update(rune_policies(ServicePolicy))
SERVICES = MappingProxyType(_POLICIES)

def catalog():
    return [{"service_id": p.service_id, "credits": p.credits,
             "min_balance": p.min_balance, "cooldown_seconds": p.cooldown_seconds,
             "async_job": p.async_job, "provider": p.provider,
             "fallback": p.fallback} for p in SERVICES.values()]
