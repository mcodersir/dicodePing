from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from .constants import MAX_SAVED_SERVERS
from .diagnostics import get_logger
from .geo import GeoResolver, flag_from_code
from .i18n import tr
from .models import DiscoveredConfig, ServerRecord, utc_now
from .net import ping_many
from .protocols import config_to_blob, parse_endpoint, record_id, set_display_name
from .storage import JsonStore

LOGGER = get_logger("service")

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]


def _sort_key(server: ServerRecord) -> tuple[int, int, int, str]:
    return (
        0 if server.favorite else 1,
        server.ping_ms if server.ping_ms is not None else 999999,
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

        # Keep responsive configs first, but retain unresponsive ones for manual mode.
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
            ping_ms = ping.ping_ms if ping else None
            ip = ping.ip if ping else ""
            geo = geo_map.get(ip, {})
            country = str(geo.get("country") or tr(language, "unknown"))
            code = str(geo.get("country_code") or "")
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
        records.sort(key=_sort_key)
        self.store.save_servers(records)
        return records

    def best_server(self, records: list[ServerRecord] | None = None) -> ServerRecord | None:
        candidates = records if records is not None else self.store.load_servers()
        online = [server for server in candidates if server.status == "online" and server.ping_ms is not None]
        return min(online, key=lambda server: server.ping_ms or 999999) if online else None

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
