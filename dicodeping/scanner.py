from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

from .crawler import crawl_telegram_channels, load_channel_specs, verify_telegram_route
from .models import ServerRecord, utc_now
from .service import AppService

SCANNER_SOURCE_ID = "scanner-sub"
SCANNER_SOURCE_NAME = "Scanner"


@dataclass(slots=True)
class ScanResult:
    crawled_configs: int
    reachable_configs: int
    servers: list[ServerRecord]


def _id(identity: str) -> str:
    return hashlib.sha256(f"{SCANNER_SOURCE_ID}\0{identity}".encode()).hexdigest()[:24]


def run_scan(
    service: AppService,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> ScanResult:
    """Discover Telegram profiles through the runtime, then real-probe them."""
    def emit(message: str) -> None:
        if log:
            log(message)

    rows = service.servers()
    if not rows:
        emit("Refreshing the authoritative subscription…")
        rows = service.refresh(language="fa")
    bootstrap = service.select_best()
    if bootstrap is None:
        raise RuntimeError("No bootstrap server is available")

    specs = load_channel_specs()
    if not specs:
        raise RuntimeError("Scanner channel list is empty")
    channels = [spec.name for spec in sorted(specs, key=lambda x: (x.rank, x.name.casefold()))]
    limits = {spec.name: (8 if spec.rank == 1 else 9) for spec in specs}

    emit(f"Connecting bootstrap: {bootstrap.name}")
    service.connect(bootstrap, tun=False, system_proxy="unchanged")
    try:
        status = service.runtime.status()
        socks_port = int(status.get("socks_port") or 0)
        if socks_port <= 0:
            raise RuntimeError("Runtime did not expose its local SOCKS port")
        route = verify_telegram_route(
            channels,
            per_channel_limits=limits,
            timeout=8.0,
            socks_port=socks_port,
            attempts=min(4, len(channels)),
        )
        if not route.ok:
            raise RuntimeError(f"Telegram route is unavailable: {route.error}")
        emit(f"Telegram route verified through {route.transport}")
        candidates = crawl_telegram_channels(
            channels=channels,
            per_channel_limits=limits,
            max_workers=12,
            timeout=7.0,
            retry_limit=0,
            socks_port=socks_port,
            max_unique_configs=120,
            minimum_channels_before_target=min(32, len(channels)),
            progress=progress,
            result_callback=(lambda result, done, total: emit(
                f"[{done}/{total}] {result.channel}: {result.picked} config(s)" if result.ok
                else f"[{done}/{total}] {result.channel}: failed"
            )),
        )
    finally:
        service.disconnect()

    candidates = candidates[:120]
    if not candidates:
        raise RuntimeError("Scanner did not discover supported proxy configurations")
    emit(f"Real-probing {len(candidates)} candidate profiles…")
    probed = service.runtime.probe_payload("\n".join(candidates))
    alive = [row for row in probed if row.get("ping_ms") is not None and isinstance(row.get("profile"), dict)]
    if not alive:
        raise RuntimeError("No discovered profile passed real latency verification")

    survivor_uris = [str(row["profile"].get("share_uri") or "") for row in alive]
    survivor_uris = [uri for uri in survivor_uris if uri]
    if not survivor_uris:
        raise RuntimeError("Verified profiles could not be exported by the runtime")

    persistent = service.runtime.sync_source(SCANNER_SOURCE_ID, "\n".join(survivor_uris))
    ping_by_uri = {
        str(row["profile"].get("share_uri") or ""): int(row["ping_ms"])
        for row in alive
        if row.get("ping_ms") is not None
    }
    old = {row.id: row for row in service.store.load_servers()}
    scanner_rows: list[ServerRecord] = []
    for idx, profile in enumerate(persistent, 1):
        profile_id = str(profile.get("id") or "")
        if not profile_id:
            continue
        uri = str(profile.get("share_uri") or "")
        record_id = _id(uri or profile_id)
        previous = old.get(record_id)
        scanner_rows.append(ServerRecord(
            id=record_id,
            name=str(profile.get("name") or f"Scanner {idx:02d}"),
            protocol=str(profile.get("type") or "UNKNOWN").upper(),
            host=str(profile.get("host") or ""),
            port=int(profile.get("port") or 0),
            config_blob=uri,
            core_profile_id=profile_id,
            network=str(profile.get("network") or ""),
            transport_security=str(profile.get("security") or ""),
            source_id=SCANNER_SOURCE_ID,
            source_name=SCANNER_SOURCE_NAME,
            source_order=10_000,
            ping_ms=ping_by_uri.get(uri),
            status="online" if ping_by_uri.get(uri) is not None else "unverified",
            favorite=previous.favorite if previous else False,
            last_checked=utc_now(),
            last_connected=previous.last_connected if previous else "",
        ))

    retained = [row for row in service.store.load_servers() if row.source_id != SCANNER_SOURCE_ID]
    merged = retained + scanner_rows
    merged.sort(key=service._sort_key)
    service.store.save_servers(merged)
    emit(f"Scanner saved {len(scanner_rows)} verified profiles")
    return ScanResult(len(candidates), len(scanner_rows), scanner_rows)
