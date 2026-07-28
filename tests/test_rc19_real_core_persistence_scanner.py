from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_android_external_core_stop_covers_registration_and_runtime():
    process = read("dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidExternalCoreProcess.kt")
    service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    assert "registrationProcess" in process
    assert "stopRequested = true" in process
    assert "registration?.stopCompat(750L)" in process
    assert "externalCore = helper" in service
    assert "runCatching { externalCore?.stop() }" in service

def test_scanner_local_source_and_servers_survive_refresh():
    settings = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/SettingsStore.kt")
    repository = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    desktop = read("dicodeping/service.py")
    assert "!isLocalScannerSource(source)" in settings
    assert "val localServers = servers.value.filter" in repository
    assert "unique + localServers" in repository
    assert "local_scanner = [row for row in old.values()" in desktop

def test_scanner_uses_one_tcp_and_one_xray_attempt():
    repository = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    scanner = read("dicodeping/scanner.py")
    assert "SCANNER_TCP_PREFILTER_WORKERS = 16" in repository
    assert "SCANNER_TEST_ATTEMPTS = 2" in repository
    assert "SCAN_PROBE_ATTEMPTS = 1" in scanner
    assert "SCAN_PROBE_MIN_SUCCESS = 1" in scanner

def test_server_duration_badges_are_human_readable():
    detector = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/VolumeDetector.kt")
    adapter = read("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ServerAdapter.kt")
    assert '"$amount days validity"' in detector
    assert "R.plurals.server_validity_days" in adapter
    assert '"${amount}d"' not in detector

def test_scanner_log_is_incremental_and_tail_following():
    android = read("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    desktop = read("dicodeping/ui.py")
    assert "val canAppend" in android
    assert "scannerLogText.append" in android
    assert "setMaximumBlockCount(800)" in desktop
    assert "ensureCursorVisible()" in desktop
