from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_xray_start_waits_for_the_real_running_state() -> None:
    bridge = read("dicodePing_android/app/src/main/java/ir/dicode/ping/xray/CoreBridge.kt")
    assert "awaitRunning()" in bridge
    assert "CORE_START_TIMEOUT_MS = 4_000L" in bridge
    assert "CORE_START_POLL_MS = 50L" in bridge
    assert "Xray core did not enter the running state within the startup deadline" in bridge


def test_vpn_service_does_not_replay_stale_connect_intents() -> None:
    service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    assert "START_NOT_STICKY" in service
    assert "START_REDELIVER_INTENT" not in service
    assert "if (core?.isRunning() != true)" in service
    assert "VpnStateStore.state.value = VpnState()" in service


def test_scanner_has_runtime_preflight_deadlines_and_atomic_stage1_cache() -> None:
    coordinator = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    assert "Embedded Xray core is unavailable on this device/ABI" in coordinator
    assert "CRAWL_TIMEOUT_MS = 4 * 60_000L" in coordinator
    assert "PROBE_TIMEOUT_MS = 14 * 60_000L" in coordinator
    assert "STAGE1_CACHE_MAX_AGE_MS = 12 * 60 * 60_000L" in coordinator
    assert "atomicWrite(" in coordinator
    assert "loadFreshStage1Cache()" in coordinator


def test_scanner_keeps_only_protocols_supported_by_the_android_parser() -> None:
    crawler = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt")
    parser = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/ConfigParser.kt")
    for scheme in ("vmess", "vless", "trojan", "ss"):
        assert scheme in crawler.lower()
        assert scheme in parser.lower()
    assert "hysteria2" not in crawler.lower()
    assert "tuic" not in crawler.lower()
