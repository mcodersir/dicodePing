from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from .constants import MAX_SAVED_SERVERS
from .diagnostics import get_logger
from .geo import GeoResolver
from .i18n import tr
from .models import DiscoveredConfig, ServerRecord, utc_now
from .net import ping_many
from .protocols import config_to_blob, parse_endpoint, record_id, set_display_name
from .storage import JsonStore

LOGGER = get_logger("service")

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]

MIN_TRUSTED_AUTO_PING_MS = 40
MAX_TRUSTED_AUTO_PING_MS = 5_000
# v1.6.0-rc.3: weight the failure history and recent-connection bonus
# into the auto-selection sort key so the chosen server is not just the
# lowest-ping one but also the most reliable one.
FAILURE_PENALTY_MS = 80          # each failure adds this many ms to the effective ping
RECENT_CONNECT_BONUS_MS = 30     # a server connected to in the last hour gets this discount
UNKNOWN_COUNTRY_PENALTY_MS = 120 # servers with no resolved country are demoted
_UNKNOWN_COUNTRIES = {"", "unknown", "نامشخص", "n/a", "-"}
_RESTRICTED_COUNTRY_CODES = {"IR"}
_RESTRICTED_COUNTRY_NAMES = {"iran", "islamic republic of iran", "ایران", "جمهوری اسلامی ایران"}


def _has_trusted_location(server: ServerRecord) -> bool:
    return (
        len(server.country_code.strip()) == 2
        and server.country.strip().casefold() not in _UNKNOWN_COUNTRIES
        and bool(server.ip and server.ip != "dns")
    )


def _has_trusted_ping(value: int | None) -> bool:
    return value is not None and MIN_TRUSTED_AUTO_PING_MS <= value <= MAX_TRUSTED_AUTO_PING_MS


def is_restricted_location(server: ServerRecord) -> bool:
    """Do not offer a locally located relay as a connection target.

    Country code is authoritative when available.  The name check is only a
    fallback for providers that returned a country name but omitted its code.
    """
    code = str(server.country_code or "").strip().upper()
    country = str(server.country or "").strip().casefold()
    return code in _RESTRICTED_COUNTRY_CODES or country in _RESTRICTED_COUNTRY_NAMES


def _is_auto_candidate(server: ServerRecord) -> bool:
    return (
        server.status == "online"
        and _has_trusted_ping(server.ping_ms)
        and _has_trusted_location(server)
        and not is_restricted_location(server)
    )


def _effective_ping_ms(server: ServerRecord) -> int:
    """Compute an effective ping that accounts for failure history and
    recent-connection bonus.

    The raw ping is adjusted by:
      + FAILURE_PENALTY_MS per recorded failure (rewards reliability)
      - RECENT_CONNECT_BONUS_MS if the server was connected to recently
      + UNKNOWN_COUNTRY_PENALTY_MS if the country is not resolved

    The result is clamped to a non-negative int.  Servers with no ping
    at all return a very large number so they sort to the bottom.
    """
    if server.ping_ms is None:
        return 999_999
    effective = int(server.ping_ms)
    effective += min(5, server.failures) * FAILURE_PENALTY_MS
    if server.last_connected:
        try:
            from datetime import datetime, timezone
            # last_connected is ISO format; parse and compare to one hour ago.
            last = datetime.fromisoformat(server.last_connected)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if (now - last).total_seconds() < 3600:
                effective -= RECENT_CONNECT_BONUS_MS
        except Exception:
            pass
    if not _has_trusted_location(server):
        effective += UNKNOWN_COUNTRY_PENALTY_MS
    return max(0, effective)


def _sort_key(server: ServerRecord) -> tuple[int, int, int, int, str]:
    return (
        0 if server.favorite else 1,
        0 if _is_auto_candidate(server) else 1,
        _effective_ping_ms(server),
        server.source_order,
        server.name.casefold(),
    )


def _as_entries(raw_configs: Iterable[str | DiscoveredConfig]) -> list[DiscoveredConfig]:
    result: list[DiscoveredConfig] = []
    for raw in raw_configs:
        if isinstance(raw, DiscoveredConfig):
            result.append(raw)
        else:
            result.append(DiscoveredConfig(str(raw), "default", "منبع اصلی", 0))
    return result


class ServerService:
    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self.geo = GeoResolver(store)

    @staticmethod
    def is_restricted_location(server: ServerRecord) -> bool:
        """Expose the shared policy through the service API used by the UI."""
        return is_restricted_location(server)

    def build_and_save(
        self,
        raw_configs: list[str | DiscoveredConfig],
        stage: StageCallback | None = None,
        progress: ProgressCallback | None = None,
        language: str = "fa",
        ping_progress: ProgressCallback | None = None,
        geo_progress: ProgressCallback | None = None,
    ) -> list[ServerRecord]:
        endpoints: list[tuple[str, object, DiscoveredConfig]] = []
        seen: set[str] = set()
        for entry in _as_entries(raw_configs):
            endpoint = parse_endpoint(entry.raw)
            if not endpoint:
                continue
            server_id = record_id(entry.raw)
            if server_id in seen:
                continue
            seen.add(server_id)
            endpoints.append((server_id, endpoint, entry))

        if stage:
            stage(tr(language, "testing_ping"))
        unique_hosts = list(dict.fromkeys(endpoint.host for _, endpoint, _ in endpoints))
        ping_callback = ping_progress or progress
        ping_results = ping_many([(host, host) for host in unique_hosts], workers=64, callback=ping_callback)
        ping_map = {item.key: item for item in ping_results}

        endpoints.sort(
            key=lambda item: (
                0 if ping_map.get(item[1].host) and ping_map[item[1].host].ping_ms is not None else 1,
                ping_map[item[1].host].ping_ms if ping_map.get(item[1].host) and ping_map[item[1].host].ping_ms is not None else 999999,
                item[2].source_order,
            )
        )
        selected = endpoints[:MAX_SAVED_SERVERS]
        if not selected:
            raise RuntimeError(tr(language, "source_fetch_failed"))

        if stage:
            stage(tr(language, "resolving_location"))
        ips = [ping_map.get(endpoint.host).ip for _, endpoint, _ in selected if ping_map.get(endpoint.host) and ping_map.get(endpoint.host).ip]
        geo_map = self.geo.resolve_many(ips, callback=geo_progress or progress)
        old = {server.id: server for server in self.store.load_servers()}
        per_source_index: dict[str, int] = defaultdict(int)

        records: list[ServerRecord] = []
        for server_id, endpoint, entry in selected:
            per_source_index[entry.source_id] += 1
            ping = ping_map.get(endpoint.host)
            raw_ping_ms = ping.ping_ms if ping else None
            ip = ping.ip if ping else ""
            geo = geo_map.get(ip, {})
            country = str(geo.get("country") or tr(language, "unknown"))
            code = str(geo.get("country_code") or "").upper()
            location_ok = len(code) == 2 and country.strip().casefold() not in _UNKNOWN_COUNTRIES
            ping_ms = raw_ping_ms if _has_trusted_ping(raw_ping_ms) and location_ok else None
            index = per_source_index[entry.source_id]
            if language != "en":
                label = f"سرور {country} • {index:02d}"
            else:
                label = f"Server {country} • {index:02d}"
            previous = old.get(server_id)
            final_name = previous.name if previous and previous.name else label
            clean_raw = set_display_name(endpoint.raw, final_name)
            records.append(
                ServerRecord(
                    id=server_id,
                    name=final_name,
                    protocol=endpoint.protocol.upper(),
                    host=endpoint.host,
                    port=endpoint.port,
                    config_blob=config_to_blob(clean_raw),
                    ping_ms=ping_ms,
                    ip=ip,
                    country=country,
                    country_code=code,
                    region=str(geo.get("region") or ""),
                    city=str(geo.get("city") or ""),
                    isp=str(geo.get("isp") or ""),
                    asn=str(geo.get("asn") or ""),
                    geo_provider=str(geo.get("geo_provider") or ""),
                    geo_confidence=str(geo.get("geo_confidence") or ""),
                    source_id=entry.source_id,
                    source_name=entry.source_name,
                    source_order=entry.source_order,
                    status="online" if ping_ms is not None else "unverified",
                    favorite=previous.favorite if previous else False,
                    last_checked=utc_now(),
                    last_connected=previous.last_connected if previous else "",
                    failures=0 if ping_ms is not None else ((previous.failures + 1) if previous else 1),
                )
            )
        records.sort(key=_sort_key)
        self.store.save_servers(records)
        LOGGER.info("Saved %d servers after discovery", len(records))
        return records

    def refresh_saved(
        self,
        stage: StageCallback | None = None,
        progress: ProgressCallback | None = None,
        language: str = "fa",
        ping_progress: ProgressCallback | None = None,
        geo_progress: ProgressCallback | None = None,
    ) -> list[ServerRecord]:
        records = self.store.load_servers()
        if not records:
            return []
        if stage:
            stage(tr(language, "refreshing_saved"))
        unique_hosts = list(dict.fromkeys(server.host for server in records if server.host))
        results = ping_many([(host, host) for host in unique_hosts], workers=64, callback=ping_progress or progress)
        result_map = {result.key: result for result in results}
        for server in records:
            result = result_map.get(server.host)
            server.last_checked = utc_now()
            if result:
                server.ip = result.ip or server.ip
            if result and result.ping_ms is not None:
                server.ping_ms = result.ping_ms
                server.status = "online"
                server.failures = 0
            else:
                server.ping_ms = None
                server.status = "unverified"
                server.failures += 1

        all_ips = [server.ip for server in records if server.ip and server.ip != "dns"]
        if stage:
            stage(tr(language, "resolving_location"))
        geo_map = self.geo.resolve_many(all_ips, callback=geo_progress or progress)
        for server in records:
            geo = geo_map.get(server.ip, {})
            if not geo:
                continue
            server.country = str(geo.get("country") or server.country)
            server.country_code = str(geo.get("country_code") or server.country_code)
            server.region = str(geo.get("region") or server.region)
            server.city = str(geo.get("city") or server.city)
            server.isp = str(geo.get("isp") or server.isp)
            server.asn = str(geo.get("asn") or server.asn)
            server.geo_provider = str(geo.get("geo_provider") or server.geo_provider)
            server.geo_confidence = str(geo.get("geo_confidence") or server.geo_confidence)
        for server in records:
            if not (_has_trusted_ping(server.ping_ms) and _has_trusted_location(server)):
                server.ping_ms = None
                server.status = "unverified"
        records.sort(key=_sort_key)
        self.store.save_servers(records)
        # Persist the fresh results into the short-lived cache so the
        # next launch can reuse them for up to 20 minutes.
        try:
            from . import ping_cache
            ping_cache.update_cache(records)
        except Exception:
            LOGGER.exception("ping_cache: update failed after refresh_saved")
        return records

    def refresh_saved_with_cache(
        self,
        stage: StageCallback | None = None,
        progress: ProgressCallback | None = None,
        language: str = "fa",
        ping_progress: ProgressCallback | None = None,
        geo_progress: ProgressCallback | None = None,
    ) -> list[ServerRecord]:
        """Like ``refresh_saved`` but reuse cached ping/location for ~20 min.

        Servers whose cache is still fresh are returned as-is with their
        cached ping/location.  Only genuinely new or stale servers are
        re-probed.  This is the fast path used by the splash screen so
        the user does not have to wait for a full re-ping on every
        launch.
        """
        from . import ping_cache

        records = self.store.load_servers()
        if not records:
            return []
        cached, fresh = ping_cache.apply_cached_to_records(records)
        LOGGER.info(
            "refresh_saved_with_cache: %d cached, %d fresh out of %d",
            len(cached), len(fresh), len(records),
        )
        if not fresh:
            # Everything is fresh — just sort and return.
            all_records = cached
            all_records.sort(key=_sort_key)
            self.store.save_servers(all_records)
            if stage:
                stage(tr(language, "update_done"))
            return all_records

        if stage:
            stage(tr(language, "refreshing_saved"))
        unique_hosts = list(dict.fromkeys(server.host for server in fresh if server.host))
        results = ping_many([(host, host) for host in unique_hosts], workers=64, callback=ping_progress or progress)
        result_map = {result.key: result for result in results}
        for server in fresh:
            result = result_map.get(server.host)
            server.last_checked = utc_now()
            if result:
                server.ip = result.ip or server.ip
            if result and result.ping_ms is not None:
                server.ping_ms = result.ping_ms
                server.status = "online"
                server.failures = 0
            else:
                server.ping_ms = None
                server.status = "unverified"
                server.failures += 1

        all_ips = [server.ip for server in fresh if server.ip and server.ip != "dns"]
        if all_ips:
            if stage:
                stage(tr(language, "resolving_location"))
            geo_map = self.geo.resolve_many(all_ips, callback=geo_progress or progress)
            for server in fresh:
                geo = geo_map.get(server.ip, {})
                if not geo:
                    continue
                server.country = str(geo.get("country") or server.country)
                server.country_code = str(geo.get("country_code") or server.country_code)
                server.region = str(geo.get("region") or server.region)
                server.city = str(geo.get("city") or server.city)
                server.isp = str(geo.get("isp") or server.isp)
                server.asn = str(geo.get("asn") or server.asn)
                server.geo_provider = str(geo.get("geo_provider") or server.geo_provider)
                server.geo_confidence = str(geo.get("geo_confidence") or server.geo_confidence)
        for server in fresh:
            if not (_has_trusted_ping(server.ping_ms) and _has_trusted_location(server)):
                server.ping_ms = None
                server.status = "unverified"

        all_records = cached + fresh
        all_records.sort(key=_sort_key)
        self.store.save_servers(all_records)
        # Persist the fresh results so the next launch can reuse them.
        try:
            ping_cache.update_cache(fresh)
        except Exception:
            LOGGER.exception("ping_cache: update failed after refresh_saved_with_cache")
        return all_records

    def refresh_subset(
        self,
        server_ids: Iterable[str],
        stage: StageCallback | None = None,
        progress: ProgressCallback | None = None,
        language: str = "fa",
        ping_progress: ProgressCallback | None = None,
        geo_progress: ProgressCallback | None = None,
    ) -> list[ServerRecord]:
        """Re-ping only the servers whose IDs are in ``server_ids``.

        Used by the source-scoped ping/volume action on the Servers
        page: when the user has a specific source tab active, we only
        re-probe that source's servers, not the whole list.
        """
        target_ids = set(server_ids)
        records = self.store.load_servers()
        if not records or not target_ids:
            return records
        subset = [r for r in records if r.id in target_ids]
        if not subset:
            return records
        if stage:
            stage(tr(language, "refreshing_saved"))
        unique_hosts = list(dict.fromkeys(server.host for server in subset if server.host))
        results = ping_many([(host, host) for host in unique_hosts], workers=64, callback=ping_progress or progress)
        result_map = {result.key: result for result in results}
        for server in subset:
            result = result_map.get(server.host)
            server.last_checked = utc_now()
            if result:
                server.ip = result.ip or server.ip
            if result and result.ping_ms is not None:
                server.ping_ms = result.ping_ms
                server.status = "online"
                server.failures = 0
            else:
                server.ping_ms = None
                server.status = "unverified"
                server.failures += 1
        for server in subset:
            if not (_has_trusted_ping(server.ping_ms) and _has_trusted_location(server)):
                server.ping_ms = None
                server.status = "unverified"
        records.sort(key=_sort_key)
        self.store.save_servers(records)
        try:
            from . import ping_cache
            ping_cache.update_cache(subset)
        except Exception:
            LOGGER.exception("ping_cache: update failed after refresh_subset")
        return records


    def auto_candidates(self, records: list[ServerRecord] | None = None) -> list[ServerRecord]:
        candidates = records if records is not None else self.store.load_servers()
        return sorted(
            (server for server in candidates if _is_auto_candidate(server)),
            key=lambda server: (server.ping_ms or 999999, server.failures, server.source_order),
        )

    def best_server(self, records: list[ServerRecord] | None = None) -> ServerRecord | None:
        candidates = self.auto_candidates(records)
        return candidates[0] if candidates else None

    def mark_probe_failed(self, server_id: str) -> None:
        records = self.store.load_servers()
        for server in records:
            if server.id == server_id:
                server.status = "unverified"
                server.ping_ms = None
                server.failures += 1
                server.last_checked = utc_now()
                break
        records.sort(key=_sort_key)
        self.store.save_servers(records)

    def update_connected(self, server_id: str) -> None:
        records = self.store.load_servers()
        for server in records:
            if server.id == server_id:
                server.last_connected = utc_now()
                server.failures = 0
                break
        self.store.save_servers(records)

    def toggle_favorite(self, server_id: str) -> list[ServerRecord]:
        records = self.store.load_servers()
        for server in records:
            if server.id == server_id:
                server.favorite = not server.favorite
                break
        records.sort(key=_sort_key)
        self.store.save_servers(records)
        return records
