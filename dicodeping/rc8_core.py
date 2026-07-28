from __future__ import annotations

from collections.abc import Iterable, Mapping


def primary_action_key(
    *,
    connected: bool,
    busy: bool,
    has_servers: bool,
    manual: bool,
    has_selected: bool,
    has_best: bool,
) -> str:
    if connected:
        return "disconnect"
    if busy:
        return "busy"
    if not has_servers:
        return "update_servers"
    if manual:
        return "connect" if has_selected else "select_server"
    return "connect" if has_best else "refresh_ping"


def responsive_server_columns(viewport_width: int) -> dict[int, bool]:
    """Return column visibility using the table viewport, not window width."""
    width = max(0, int(viewport_width))
    return {
        2: width >= 720,  # location
        3: width >= 900,  # address
        5: width >= 620,  # favorite
    }


def geo_lookup_ips(records: Iterable[object]) -> list[str]:
    """Only responsive rows need fresh location data."""
    return list(
        dict.fromkeys(
            str(getattr(row, "ip", ""))
            for row in records
            if getattr(row, "status", "") == "online"
            and getattr(row, "ping_ms", None) is not None
            and str(getattr(row, "ip", ""))
        )
    )


def unresolved_retry_hosts(
    failed_endpoints: Iterable[tuple[str, int]],
    resolved: Mapping[tuple[str, int], list[str]],
) -> list[str]:
    """DNS failures must be resolved again before a retry can help."""
    return list(dict.fromkeys(host for host, port in failed_endpoints if not resolved.get((host, port))))


def is_current_worker(active_worker: object | None, finished_worker: object | None) -> bool:
    return finished_worker is None or active_worker is finished_worker
