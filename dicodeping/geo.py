from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
from typing import Callable

from .constants import GEO_CACHE_TTL_DAYS
from .diagnostics import get_logger
from .net import lookup_geo, lookup_geo_fast
from .storage import JsonStore


GEO_CACHE_SCHEMA = 5
LOGGER = get_logger("geo")


def _fresh(entry: dict) -> bool:
    if entry.get("_schema") != GEO_CACHE_SCHEMA:
        return False
    stamp = str(entry.get("_cached_at") or "")
    if not stamp:
        return False
    try:
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        ttl = timedelta(minutes=30) if entry.get("_failed") else timedelta(days=GEO_CACHE_TTL_DAYS)
        return datetime.now(timezone.utc) - moment < ttl
    except Exception:
        return False


class GeoResolver:
    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self.cache = store.load_geo_cache()

    def resolve_many(
        self,
        ips: list[str],
        callback: Callable[[int, int], None] | None = None,
        *,
        fast: bool = False,
        force_refresh: bool = False,
        result_callback: Callable[[str, dict[str, str]], None] | None = None,
    ) -> dict[str, dict[str, str]]:
        unique = list(dict.fromkeys(ip for ip in ips if ip and ip != "dns"))
        missing = list(unique) if force_refresh else [ip for ip in unique if ip not in self.cache or not _fresh(self.cache.get(ip, {}))]
        total = len(missing)
        done = 0
        if missing:
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
                resolver = lookup_geo_fast if fast else lookup_geo
                futures = {executor.submit(resolver, ip): ip for ip in missing}
                for future in concurrent.futures.as_completed(futures):
                    ip = futures[future]
                    try:
                        value = future.result() or {}
                    except Exception as exc:
                        LOGGER.warning("Geo lookup failed for %s: %s", ip, exc)
                        value = {}
                    if value:
                        value["_cached_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                        value["_schema"] = GEO_CACHE_SCHEMA
                        self.cache[ip] = value
                    elif ip not in self.cache:
                        self.cache[ip] = {
                            "_cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "_failed": True,
                            "_schema": GEO_CACHE_SCHEMA,
                        }
                    done += 1
                    public_value = {key: item for key, item in self.cache.get(ip, {}).items() if not key.startswith("_")}
                    if result_callback:
                        result_callback(ip, public_value)
                    if callback:
                        callback(done, total)
            self.store.save_geo_cache(self.cache)
        return {ip: {key: value for key, value in self.cache.get(ip, {}).items() if not key.startswith("_")} for ip in unique}


def flag_from_code(code: str) -> str:
    value = code.strip().upper()
    if len(value) != 2 or not value.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in value)
