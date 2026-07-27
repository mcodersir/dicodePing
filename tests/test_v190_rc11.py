from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_desktop_scanner_notice_is_persistent_and_home_owned() -> None:
    ui = read("dicodeping/ui.py")
    assert 'scanner_vpn_notice_seen' in ui
    assert 'self.store.save_settings(self.settings)' in ui
    assert 'self.switch_page(0)' in ui
    assert 'QTimer.singleShot(120, self.connect_best)' in ui
    assert 'QTimer.singleShot(180, self._resume_pending_scanner)' in ui
    assert 'if not self.manager.connected or not self.connected_id' in ui


def test_android_scanner_never_requests_vpn_permission_or_starts_vpn() -> None:
    fragment = read("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    coordinator = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    assert "host.requestScannerLaunch()" in fragment
    assert "VpnService.prepare" not in fragment
    assert "DicodeVpnService.EXTRA_CONFIG" not in coordinator
    assert "requireConnectedBootstrap()" in coordinator
    assert "connectBootstrap()" not in coordinator


def test_android_home_owns_one_time_notice_connection_and_resume() -> None:
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    settings = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/SettingsStore.kt")
    assert "scannerVpnNoticeSeen" in settings
    assert "settings.scannerVpnNoticeSeen = true" in activity
    assert "showPage(R.id.nav_home)" in activity
    assert 'vm.repo.settings.activeCore = "xray"' in activity
    assert "connect(null)" in activity
    assert "launchScannerAfterConnection()" in activity
    assert "pendingScannerStart = false" in activity


def test_android_pending_scanner_survives_activity_recreation_until_service_start() -> None:
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    assert 'outState.putBoolean(KEY_PENDING_SCANNER, pendingScannerStart)' in activity
    block = activity.split("private fun launchScannerAfterConnection()", 1)[1].split(
        "private fun failPendingScannerConnection", 1
    )[0]
    assert "Keep the pending flag until startForegroundService succeeds" in block
    assert ".onSuccess {" in block
    assert "pendingScannerStart = false" in block


def test_android_telegram_failure_gives_actionable_guidance() -> None:
    coordinator = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    english = read("dicodePing_android/app/src/main/res/values/strings.xml")
    persian = read("dicodePing_android/app/src/main/res/values-fa/strings.xml")
    assert "scanner_telegram_unreachable" in coordinator
    assert "server configuration, internet access, and VPN permission" in english
    assert "کانفیگ سرور انتخابی، اینترنت و مجوز VPN" in persian


def test_android_vpn_revoke_uses_serialized_cleanup_without_default_stop_race() -> None:
    service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    revoke = service.split("override fun onRevoke()", 1)[1].split("override fun onDestroy()", 1)[0]
    assert "stopVpn()" in revoke
    assert "super.onRevoke()" not in revoke
    assert "runtimeMutex.withLock { stopRuntime() }" in service
    assert "previousStart?.cancelAndJoin()" in service


def test_android_scanner_foreground_transition_is_guarded() -> None:
    service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerService.kt")
    assert "startForegroundSafely" in service
    assert 'AppLog.e("ScannerService", "Cannot enter foreground state"' in service
    assert "return START_NOT_STICKY" in service


def test_rc12_release_files_and_versions_are_consistent() -> None:
    workflow = read(".github/workflows/v1.9.0-rc.12-release.yml")
    notes = read("docs/releases/v1.9.0-rc.12.md")
    gradle = read("dicodePing_android/app/build.gradle.kts")
    constants = read("dicodeping/constants.py")
    assert "v1.9.0-rc.12" in workflow
    assert "DEPLOY_PRERELEASE_RC12.bat" in {path.name for path in ROOT.iterdir()}
    assert 'versionName = "1.9.0-rc.12"' in gradle
    assert 'RELEASE_VERSION = "1.9.0-rc.12"' in constants
    assert "## فارسی" in notes and "## English" in notes
