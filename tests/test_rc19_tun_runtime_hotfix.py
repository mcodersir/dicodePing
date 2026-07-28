from __future__ import annotations

import socket
import threading
from pathlib import Path

from dicodeping.models import ServerRecord
from dicodeping.service import ServerService
from dicodeping.xray import _read_http_status, _recv_exact

ROOT = Path(__file__).resolve().parents[1]


class MemoryStore:
    def __init__(self, rows: list[ServerRecord]) -> None:
        self.rows = list(rows)

    def load_servers(self) -> list[ServerRecord]:
        return [ServerRecord.from_dict(item.to_dict()) for item in self.rows]

    def save_servers(self, servers: list[ServerRecord]) -> None:
        self.rows = [ServerRecord.from_dict(item.to_dict()) for item in servers]

    def load_geo_cache(self) -> dict:
        return {}

    def save_geo_cache(self, cache: dict) -> None:
        _ = cache


def _server(server_id: str = "scanner-server") -> ServerRecord:
    return ServerRecord(
        id=server_id,
        name="Scanner server",
        protocol="VLESS",
        host="example.com",
        port=443,
        config_blob="blob",
        ping_ms=120,
        ip="203.0.113.8",
        country="Test",
        country_code="US",
        source_id="scanner-sub",
        status="online",
    )


def test_mark_probe_failed_never_references_missing_old_mapping() -> None:
    store = MemoryStore([_server()])
    service = ServerService(store)  # type: ignore[arg-type]
    service.mark_probe_failed("scanner-server")
    assert len(store.rows) == 1
    assert store.rows[0].source_id == "scanner-sub"
    assert store.rows[0].status == "unverified"
    assert store.rows[0].ping_ms is None
    assert store.rows[0].failures == 1


def test_toggle_favorite_preserves_scanner_server_without_name_error() -> None:
    store = MemoryStore([_server()])
    service = ServerService(store)  # type: ignore[arg-type]
    rows = service.toggle_favorite("scanner-server")
    assert len(rows) == 1
    assert rows[0].favorite is True
    assert rows[0].source_id == "scanner-sub"


def test_fragmented_socket_reads_are_reassembled() -> None:
    left, right = socket.socketpair()
    try:
        def writer() -> None:
            for chunk in (b"H", b"T", b"TP/1.1 204", b" No Content\r", b"\nHeader: x\r\n\r\n"):
                right.sendall(chunk)

        thread = threading.Thread(target=writer)
        thread.start()
        assert _read_http_status(left) == 204
        thread.join(timeout=1)
    finally:
        left.close()
        right.close()


def test_recv_exact_handles_fragmented_socks_reply() -> None:
    left, right = socket.socketpair()
    try:
        def writer() -> None:
            right.sendall(b"\x05")
            right.sendall(b"\x00")

        thread = threading.Thread(target=writer)
        thread.start()
        assert _recv_exact(left, 2) == b"\x05\x00"
        thread.join(timeout=1)
    finally:
        left.close()
        right.close()


def test_private_socks_precheck_is_https_first_and_advisory() -> None:
    source = (ROOT / "dicodeping/xray.py").read_text(encoding="utf-8")
    start = source[source.index("    def start("):source.index("    def traffic_stats(")]
    assert '("www.gstatic.com", "/generate_204", True)' in start
    assert "Private SOCKS validation was inconclusive; continuing" in start
    warning_at = start.index("Private SOCKS validation was inconclusive; continuing")
    tun_probe_at = start.index("_direct_tun_http_probe", warning_at)
    assert warning_at < tun_probe_at
    assert "A failed private probe must never" in start


def test_undefined_old_mapping_exists_only_where_it_is_initialized() -> None:
    source = (ROOT / "dicodeping/service.py").read_text(encoding="utf-8")
    assert source.count("old.values()") == 1
    initialized = source.index("old = {server.id: server for server in self.store.load_servers()}")
    use = source.index("old.values()")
    assert initialized < use
