"""Event-driven, cached public system health checks."""

import asyncio
import json
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

CACHE_SECONDS = 60
NIST_URL = "https://beacon.nist.gov/beacon/2.0/pulse/last"

_snapshot = None
_snapshot_time = 0.0
_refresh_task = None
_lock = asyncio.Lock()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_nist_sync():
    """Public, nonbillable NIST Beacon check."""
    start = time.monotonic()

    try:
        request = Request(
            NIST_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "gnosis.bot-health/0.1",
            },
        )

        with urlopen(request, timeout=5) as response:
            data = json.load(response)

        pulse = data["pulse"]

        if pulse.get("statusCode") != 0:
            raise ValueError("NIST pulse status is not successful")

        if not pulse.get("outputValue"):
            raise ValueError("NIST pulse lacks outputValue")

        return {
            "status": "healthy",
            "latency_ms": round(
                (time.monotonic() - start) * 1000
            ),
            "pulse_timestamp": pulse.get("timeStamp"),
            "pulse_uri": pulse.get("uri"),
            "checked_at": utc_now(),
        }

    except Exception as exc:
        return {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "checked_at": utc_now(),
        }


async def build_snapshot():
    nist = await asyncio.to_thread(check_nist_sync)

    return {
        "schema_version": "gnosis.health.v1",
        "generated_at": utc_now(),
        "cache_ttl_seconds": CACHE_SECONDS,
        "services": {
            "oracle.classic": {
                "status": "healthy",
                "provider": "browser_crypto",
                "note": "Browser capability not independently tested",
            },
            "oracle.public_qrng": {
                "provider": "nist",
                **nist,
            },
            "oracle.qrandom": {
                "status": "unknown",
                "provider": "anu",
                "reason": "Backend integration pending",
            },
            "oracle.true_quantum": {
                "status": "unknown",
                "provider": "ibm",
                "reason": "Quantum inventory not configured",
            },
            "oracle.personal_quantum": {
                "status": "unknown",
                "provider": "ibm",
                "reason": "IBM runtime not configured",
            },
            "ai.enhancement": {
                "status": "unknown",
                "provider": "deepinfra",
                "reason": "Provider not configured",
            },
        },
        "ibm_backends": [],
    }


async def _refresh():
    global _snapshot, _snapshot_time

    try:
        result = await build_snapshot()
        async with _lock:
            _snapshot = result
            _snapshot_time = time.monotonic()
        return result
    except Exception:
        # Preserve the previous snapshot if refresh fails.
        if _snapshot is not None:
            return _snapshot
        raise


async def system_status():
    """Return cached status and refresh at most once per TTL."""
    global _refresh_task

    async with _lock:
        age = time.monotonic() - _snapshot_time

        if _snapshot is not None and age < CACHE_SECONDS:
            return {
                **_snapshot,
                "cached": True,
                "stale": False,
                "age_seconds": round(age, 1),
            }

        if _refresh_task is None or _refresh_task.done():
            _refresh_task = asyncio.create_task(_refresh())

        task = _refresh_task

        if _snapshot is not None:
            return {
                **_snapshot,
                "cached": True,
                "stale": True,
                "age_seconds": round(age, 1),
            }

    # First request waits for initial snapshot.
    result = await task
    return {
        **result,
        "cached": False,
        "stale": False,
        "age_seconds": 0,
    }