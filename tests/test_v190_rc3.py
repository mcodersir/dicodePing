from __future__ import annotations

import threading
from pathlib import Path

import dicodeping.scanner as scanner
from dicodeping.connection_manager import AlternativeCoreManager, ConnectionManager
from dicodeping.crawler import ChannelResult, ChannelSpec, crawl_telegram_channels

ROOT = Path(__file__).resolve().parents[1]


def _vless(host: str, port: int = 443) -> str:
    return (
        "vless://11111111-1111-4111-8111-111111111111@"
        f"{host}:{port}?security=tls&type=tcp#{host}"
    )


def test_rc3_release_entrypoints_and_metadata() -> None:
    assert (ROOT / "BUILD_RELEASE_RC7.bat").is_file()
    assert (ROOT / "RUN_SOURCE_RC7.bat").is_file()
    assert (ROOT / "app_v190_rc5.py").is_file()
    build = (ROOT / "BUILD_RELEASE_RC7.bat").read_text("utf-8")
    assert "--tag v1.9.0-rc.7" in build
    assert "tools\\build_windows.py --skip-install" in build
    assert "legacy-style portable Windows EXE" in build
    assert "BUILD_SIGNED_APK_RC7.bat" in build


def test_scanner_ui_uses_queued_slots_batched_logs_and_highlighting() -> None:
    source = (ROOT / "dicodeping/ui.py").read_text("utf-8")
    workers = (ROOT / "dicodeping/workers.py").read_text("utf-8")
    assert "class ScannerLogHighlighter(QSyntaxHighlighter)" in source
    assert "@Slot(object)\n    def _scanner_log_batch" in source
    assert "Qt.QueuedConnection" in source
    assert "setMaximumBlockCount(1200)" in source
    assert "scanner_speed_label" in source
    assert "RC3 intentionally removed ETA" in source
    assert "log_batch = Signal(object)" in workers
    assert "len(self._log_buffer) >= 16" in workers


def test_crawler_honors_per_channel_limits_and_reports_transfer(monkeypatch) -> None:
    calls: list[tuple[str, int, int]] = []

    def fake_fetch(channel: str, *, per_channel_limit: int, timeout: float, socks_port: int, stop_event=None):
        calls.append((channel, per_channel_limit, socks_port))
        rows = [_vless(f"{channel}-{index}.example") for index in range(per_channel_limit + 2)]
        return ChannelResult(
            channel=channel,
            ok=True,
            found=len(rows),
            picked=per_channel_limit,
            elapsed_ms=10,
            configs=rows[:per_channel_limit],
            bytes_received=2048,
            transport="socks5",
        )

    monkeypatch.setattr("dicodeping.crawler.fetch_channel", fake_fetch)
    results: list[ChannelResult] = []
    raw = crawl_telegram_channels(
        channels=["rank1", "rank2"],
        per_channel_limits={"rank1": 2, "rank2": 4},
        max_workers=16,
        result_callback=lambda result, _done, _total: results.append(result),
        socks_port=1819,
    )

    assert sorted(calls) == [("rank1", 2, 1819), ("rank2", 4, 1819)]
    assert len(raw) == 6
    assert sum(item.bytes_received for item in results) == 4096
    assert all(item.transport == "socks5" for item in results)


def test_crawl_stage_emits_speed_metrics_and_rank_limits(monkeypatch) -> None:
    captured: dict[str, object] = {}
    metrics: list[dict[str, object]] = []
    logs: list[str] = []

    monkeypatch.setattr(
        scanner,
        "load_channel_specs",
        lambda: [ChannelSpec("one", 1), ChannelSpec("two", 2)],
    )

    def fake_crawl(**kwargs):
        captured.update(kwargs)
        callback = kwargs["result_callback"]
        callback(ChannelResult("one", True, 3, 2, 20, [], bytes_received=3072), 1, 2)
        callback(ChannelResult("two", True, 5, 4, 25, [], bytes_received=5120), 2, 2)
        return [_vless("one.example"), _vless("two.example")]

    monkeypatch.setattr(scanner, "crawl_telegram_channels", fake_crawl)
    state = scanner._ProbeState(stop_requested=threading.Event())
    raw = scanner._crawl_only(
        rank1_limit=2,
        rank2_limit=4,
        socks_port=1819,
        metrics_callback=metrics.append,
        log_callback=logs.append,
        state=state,
    )

    assert captured["per_channel_limits"] == {"one": 2, "two": 4}
    assert captured["socks_port"] == 1819
    assert len(raw) == 2
    assert metrics[-1]["bytes"] == 8192
    assert metrics[-1]["configs"] == 6
    assert any("[TG][OK]" in line and "KiB/s" in line for line in logs)
    assert any("[TG][DONE]" in line and "avg=" in line for line in logs)


def test_existing_connection_is_reused_without_duplicate_connect(monkeypatch) -> None:
    connect_calls: list[str] = []
    disconnect_calls: list[bool] = []

    def stop_after_bootstrap(**_kwargs):
        raise RuntimeError("stop-after-bootstrap")

    monkeypatch.setattr(scanner, "_crawl_only", stop_after_bootstrap)

    class Store:
        pass

    import pytest

    with pytest.raises(RuntimeError, match="stop-after-bootstrap"):
        scanner.run_scan(
            store=Store(),
            bootstrap_server_id="existing-id",
            connect_callback=connect_calls.append,
            disconnect_callback=lambda: disconnect_calls.append(True),
            is_connected_callback=lambda: not disconnect_calls,
            validate_connection_callback=lambda: True,
        )

    assert connect_calls == []
    assert disconnect_calls == [True]


def test_connection_facade_exposes_alternative_socks_port() -> None:
    facade = ConnectionManager.__new__(ConnectionManager)
    manager = AlternativeCoreManager("aether")
    manager.socks_port = 1819
    facade._manager = manager
    assert facade.local_socks_port == 1819


def test_scanner_concurrency_is_fast_but_resource_bounded() -> None:
    assert 4 <= scanner.SCAN_CRAWL_WORKERS <= 12
    assert 4 <= scanner.SCAN_PROBE_WORKERS <= 12
    assert 2 <= scanner.SCAN_PROBE_RETRY_WORKERS <= 4
    assert scanner.SCAN_PROBE_QUEUE_LIMIT <= 24
