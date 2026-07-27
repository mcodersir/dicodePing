from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_usque_android_x86_64_uses_ndk_cgo_external_linking() -> None:
    prep = read("dicodePing_android/tools/prepare_bundled_cores.py")
    workflow = read(".github/workflows/v1.9.0-rc.11-release.yml")
    assert '"CGO_ENABLED": "1"' in prep
    assert '"x86_64-linux-android"' in prep
    assert '"GOARCH": goarch' in prep
    assert 'max-page-size=16384' in prep
    assert 'ndk;27.2.12479018' in workflow
    assert 'go-version: "1.26.3"' in workflow


def test_android_native_xray_batch_probes_are_process_serialized() -> None:
    bridge = read("dicodePing_android/app/src/main/java/ir/dicode/ping/xray/CoreBridge.kt")
    repository = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "synchronized(OUTBOUND_PROBE_LOCK)" in bridge
    assert "val OUTBOUND_PROBE_LOCK = Any()" in bridge
    assert "val concurrency = 1" in repository
    assert "runBatch(input, 1" in repository


def test_scanner_transaction_requires_home_connection_then_collects_disconnects_and_probes() -> None:
    coordinator = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    connected = coordinator.index("requireConnectedBootstrap()")
    crawl = coordinator.index("TelegramChannelCrawler.crawl(")
    persist = coordinator.index('scanner-stage1-raw.txt')
    disconnect = coordinator.index("disconnectStrict(ignoreFailure = false)")
    probe = coordinator.index("repo.importScannerConfigs(")
    assert connected < crawl < persist < disconnect < probe
    assert "vm.repo.connectionCandidates(AUTO_RETRY_LIMIT)" in activity
    assert "CONNECTED is published by DicodeVpnService only after" in coordinator


def test_android_services_publish_state_and_never_throw_from_ui_service_calls() -> None:
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    scanner_service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerService.kt")
    vpn_service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    assert 'runCatching { ContextCompat.startForegroundService(applicationContext, intent) }' in activity
    assert 'runCatching {' in activity and 'VPN stop request failed' in activity
    assert "ServiceCompat.startForeground(" in scanner_service
    assert "ServiceCompat.startForeground(" in vpn_service
    assert "Keep the foreground service alive until native cleanup finishes" in vpn_service


def test_automatic_mode_accepts_any_positive_real_http_ping_and_retries_diverse_candidates() -> None:
    desktop = read("dicodeping/service.py")
    android_policy = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/Models.kt")
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    assert "MIN_TRUSTED_AUTO_PING_MS = 1" in desktop
    assert "MIN_AUTO_PING_MS = 1" in android_policy
    assert "server.countryCode.isNotBlank()" not in android_policy
    assert "AUTO_RETRY_LIMIT = 8" in activity
