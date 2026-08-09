"""Short-lived ping and location cache for the splash-screen fast path.

When the user launches dicodePing, the splash screen normally re-pings
every saved server and re-resolves every location from scratch.  On a
slow connection this can take 30+ seconds, which is exactly the
experience the user complained about in v1.6.0-rc.4.

This module caches the most recent ping and location for each server
for ``CACHE_TTL_SECONDS`` (default 20 minutes).  When the splash screen
runs, it asks ``fresh_subset`` which servers still need a real probe.
Servers whose cache is fresh are reused as-is, so the splash only
probes the genuinely new or stale ones.

The cache is persisted as JSON under ``DATA_DIR / ping_cache.json`` so
it survives across restarts.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .constants import DATA_DIR
from .diagnostics import get_logger
from .models import ServerRecord

LOGGER = get_logger("ping_cache")

CACHE_FILE = DATA_DIR / "ping_cache.json"
CACHE_TTL_SECONDS = 20 * 60  # 20 minutes


@dataclass(frozen=True, slots=True)
class CachedPing:
    """A single cached ping/location snapshot for one server."""

    server_id: str
    ping_ms: int | None
    status: str
    ip: str
    country: str
    country_code: str
    region: str
    city: str
    isp: str
    asn: str
    geo_provider: str
    geo_confidence: str
    timestamp: float  # monotonic time when the cache entry was written


def _load_raw() -> dict[str, dict]:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_raw(data: dict[str, dict]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        LOGGER.exception("ping_cache: failed to save")


def _now() -> float:
    return time.time()


def read_cache() -> dict[str, CachedPing]:
    """Return the full cache as a ``{server_id: CachedPing}`` dict."""
    raw = _load_raw()
    out: dict[str, CachedPing] = {}
    for sid, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        try:
            out[sid] = CachedPing(
                server_id=str(entry.get("server_id") or sid),
                ping_ms=int(entry["ping_ms"]) if entry.get("ping_ms") is not None else None,
                status=str(entry.get("status") or "unverified"),
                ip=str(entry.get("ip") or ""),
                country=str(entry.get("country") or ""),
                country_code=str(entry.get("country_code") or ""),
                region=str(entry.get("region") or ""),
                city=str(entry.get("city") or ""),
                isp=str(entry.get("isp") or ""),
                asn=str(entry.get("asn") or ""),
                geo_provider=str(entry.get("geo_provider") or ""),
                geo_confidence=str(entry.get("geo_confidence") or ""),
                timestamp=float(entry.get("timestamp") or 0.0),
            )
        except (TypeError, ValueError, KeyError):
            continue
    return out


def is_fresh(entry: CachedPing, *, now: float | None = None, ttl: int = CACHE_TTL_SECONDS) -> bool:
    """Return True if the entry is still within its TTL window."""
    if entry is None:
        return False
    n = now if now is not None else _now()
    return (n - entry.timestamp) <= ttl


def fresh_subset(server_ids: Iterable[str], *, ttl: int = CACHE_TTL_SECONDS) -> set[str]:
    """Return the set of server IDs whose cache is still fresh.

    Use this on the splash path to decide which servers can skip the
    real ping/location probe.
    """
    cache = read_cache()
    now = _now()
    return {sid for sid in server_ids if sid in cache and is_fresh(cache[sid], now=now, ttl=ttl)}


def apply_cached_to_records(records: list[ServerRecord], *, ttl: int = CACHE_TTL_SECONDS) -> tuple[list[ServerRecord], list[ServerRecord]]:
    """Split records into ``(cached, fresh)`` based on the cache.

    The ``cached`` list contains records with their ping/location fields
    overwritten from the cache.  The ``fresh`` list contains the
    remaining records that still need a real probe.

    Both lists preserve the original record order.
    """
    cache = read_cache()
    now = _now()
    cached_out: list[ServerRecord] = []
    fresh_out: list[ServerRecord] = []
    for record in records:
        entry = cache.get(record.id)
        if entry is not None and is_fresh(entry, now=now, ttl=ttl):
            # Overwrite ping/location fields from the cache so the UI
            # shows the cached values immediately.
            cached_out.append(
                ServerRecord(
                    id=record.id,
                    name=record.name,
                    protocol=record.protocol,
                    host=record.host,
                    port=record.port,
                    config_blob=record.config_blob,
                    ping_ms=entry.ping_ms,
                    ip=entry.ip or record.ip,
                    country=entry.country or record.country,
                    country_code=entry.country_code or record.country_code,
                    region=entry.region or record.region,
                    city=entry.city or record.city,
                    isp=entry.isp or record.isp,
                    asn=entry.asn or record.asn,
                    geo_provider=entry.geo_provider or record.geo_provider,
                    geo_confidence=entry.geo_confidence or record.geo_confidence,
                    source_id=record.source_id,
                    source_name=record.source_name,
                    source_order=record.source_order,
                    status=entry.status if entry.ping_ms is not None else "unverified",
                    favorite=record.favorite,
                    last_checked=record.last_checked,
                    last_connected=record.last_connected,
                    failures=record.failures,
                )
            )
        else:
            fresh_out.append(record)
    return cached_out, fresh_out


def update_cache(records: Iterable[ServerRecord], *, now: float | None = None) -> None:
    """Write the given records' ping/location into the cache.

    Existing entries for other server IDs are preserved.  Call this
    after a real ping/location pass completes so the next launch can
    reuse the results.
    """
    raw = _load_raw()
    n = now if now is not None else _now()
    for record in records:
        raw[record.id] = {
            "server_id": record.id,
            "ping_ms": record.ping_ms,
            "status": record.status,
            "ip": record.ip,
            "country": record.country,
            "country_code": record.country_code,
            "region": record.region,
            "city": record.city,
            "isp": record.isp,
            "asn": record.asn,
            "geo_provider": record.geo_provider,
            "geo_confidence": record.geo_confidence,
            "timestamp": n,
        }
    # Trim the cache to the most recent 500 entries to keep the file
    # bounded.
    if len(raw) > 500:
        sorted_items = sorted(raw.items(), key=lambda kv: kv[1].get("timestamp") or 0.0, reverse=True)[:500]
        raw = dict(sorted_items)
    _save_raw(raw)


def clear_cache() -> None:
    """Wipe the cache file (used by the Settings 'clear data' action)."""
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        LOGGER.exception("ping_cache: failed to clear")
