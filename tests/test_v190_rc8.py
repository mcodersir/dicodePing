from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rc8_uses_full_ranked_channel_catalog_and_requested_limits() -> None:
    payload = json.loads(read("assets/channels.json"))
    channels = payload["channels"]
    assert len(channels) >= 300
    assert sum(1 for row in channels if int(row["rank"]) == 1) == 9
    scanner = read("dicodeping/scanner.py")
    assert "DEFAULT_RANK1_PER_CHANNEL = 8" in scanner
    assert "DEFAULT_RANK2_PER_CHANNEL = 9" in scanner
    android = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    assert 'fun start(name: String = "SUB", rank1: Int = 8, rank2: Int = 9)' in android


def test_scanner_persists_candidates_before_strict_disconnect_and_probe() -> None:
    scanner = read("dicodeping/scanner.py")
    crawl = scanner.index("configs = _crawl_only(")
    snapshot = scanner.index("_save_stage1_snapshot(")
    disconnect = scanner.index("[DISCONNECT][START]", crawl)
    probe = scanner.index("alive_raws = _probe_only(", disconnect)
    assert snapshot < disconnect < probe
    assert "scanner-stage1-raw.txt" in scanner
    assert "scanner-stage1-meta.json" in scanner
    assert "_wait_disconnected(SCAN_BOOTSTRAP_DISCONNECT_TIMEOUT_S)" in scanner


def test_telegram_crawler_prefers_tun_and_bounds_socks_fallback() -> None:
    crawler = read("dicodeping/crawler.py")
    assert 'routes: list[tuple[str, int]] = []' in crawler
    assert 'routes.append(("socks5", int(socks_port)))' in crawler
    assert 'routes.append(("tun", 0))' in crawler
    assert "threading.BoundedSemaphore(10)" in crawler
    assert "max_unique_configs" in crawler
    assert "minimum_channels_before_target" in crawler


def test_rc8_increases_bounded_collection_and_probe_capacity() -> None:
    scanner = read("dicodeping/scanner.py")
    assert "SCAN_CRAWL_TARGET_RAW = 180" in scanner
    assert "SCAN_CRAWL_MIN_CHANNELS = 36" in scanner
    assert "SCAN_MAX_PROBE_CONFIGS = 160" in scanner
    assert "SCAN_MAX_SERVERS = 80" in scanner
    assert "if len(state.alive) >= 5" not in scanner
    android = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "MAX_SCANNER_SERVERS = 160" in android
    assert "SCANNER_HEALTHY_TARGET = 60" in android


def test_rc8_scanner_feedback_and_server_cards_are_explicit() -> None:
    ui = read("dicodeping/ui.py")
    assert "self.scanner_connection_log_view" in ui
    assert "self.scanner_tg_log_view" in ui
    assert "self.scanner_test_log_view" in ui
    assert "def _request_scanner_launch" in ui
    assert "scanner_vpn_notice_seen" in ui
    assert "self.switch_page(0)" in ui
    assert 'f"SUB {index:03d}"' in read("dicodeping/scanner.py")
    assert "server_ping_badge" in ui or "ping_badge" in ui


def test_rc8_release_payload_is_bilingual_and_multiplatform() -> None:
    workflow = read(".github/workflows/v1.9.0-rc.13-release.yml")
    notes = read("docs/releases/v1.9.0-rc.13.md")
    deploy = read("DEPLOY_PRERELEASE_RC13.bat")
    assert "## فارسی" in notes and "## English" in notes
    for asset in (
        "dicodePing-v1.9.0-rc.13-windows-x64.exe",
        "dicodePing-v1.9.0-rc.13-linux-x86_64.tar.gz",
        "dicodePing-v1.9.0-rc.13-macos-${{ matrix.architecture }}.dmg",
        "dicodePing-v1.9.0-rc.13-android.apk",
    ):
        assert asset in workflow
    assert "v1.9.0-rc.13" in deploy
    assert "wait_for_github_release_rc13.ps1" in deploy
