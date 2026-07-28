from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_scanner_routes_vpn_permission_and_connection_through_home() -> None:
    fragment = read("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    coordinator = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    assert "host.requestScannerLaunch()" in fragment
    assert "VpnService.prepare(requireContext())" not in fragment
    assert "scannerVpnNoticeSeen" in activity
    assert "showPage(R.id.nav_home)" in activity
    assert "launchScannerAfterConnection()" in activity
    assert "ContextCompat.startForegroundService(" in activity
    assert "requireConnectedBootstrap()" in coordinator
    assert "connectBootstrap()" not in coordinator
    assert "Stopping bootstrap VPN before native probes" in coordinator


def test_android_scanner_fragment_has_no_permission_callback_or_expired_view_access() -> None:
    fragment = read("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    assert "ActivityResultContracts.StartActivityForResult" not in fragment
    assert "scannerStartPending" not in fragment
    assert "Snackbar.make(requireView()" not in fragment
    assert "private var _binding" in fragment

def test_per_app_vpn_controls_live_in_routing_section() -> None:
    layout = read("dicodePing_android/app/src/main/res/layout/fragment_settings.xml")
    routing = layout.index('android:id="@+id/bypassSection"')
    per_app = layout.index('android:id="@+id/perAppMode"')
    assert per_app > routing


def test_android_bundles_aether_and_usque_as_apk_owned_native_executables() -> None:
    preparation = read("dicodePing_android/tools/prepare_bundled_cores.py")
    process = read("dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidExternalCoreProcess.kt")
    gradle = read("dicodePing_android/app/build.gradle.kts")
    workflow = read(".github/workflows/v1.9.0-rc.13-release.yml")
    assert '"libaether.so"' in preparation
    assert '"libusque.so"' in preparation
    assert '"-buildmode=pie"' in preparation
    assert "context.applicationInfo.nativeLibraryDir" in process
    assert "context.assets.open" not in process
    assert "jniLibs.useLegacyPackaging = true" in gradle
    assert "lib/$abi/libaether.so" in workflow
    assert "lib/$abi/libusque.so" in workflow


def test_desktop_release_builders_embed_optional_working_cores() -> None:
    for builder in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        text = read(builder)
        assert "tools.prepare_optional_cores" in text
        assert "aether" in text.lower()
        assert "usque" in text.lower()
    workflow = read(".github/workflows/v1.9.0-rc.13-release.yml")
    assert "dicodePing-core-aether" not in workflow
    assert "dicodePing-core-usque" not in workflow


def test_connection_ui_publishes_feedback_before_permission_or_service_start() -> None:
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    assert "VpnStateStore.state.value = VpnState(" in activity
    assert "status = VpnStatus.CONNECTING" in activity
    assert "ServiceCompat.startForeground(" in service
    assert "AtomicBoolean(false)" in service
    assert "previousStart?.cancelAndJoin()" in service


def test_rc13_release_metadata_and_bilingual_notes_exist() -> None:
    workflow = read(".github/workflows/v1.9.0-rc.13-release.yml")
    notes = read("docs/releases/v1.9.0-rc.13.md")
    assert "v1.9.0-rc.13" in workflow
    assert "## فارسی" in notes
    assert "## English" in notes


def test_android_external_process_is_api24_compatible_and_lint_strict() -> None:
    process = read("dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidExternalCoreProcess.kt")
    gradle = read("dicodePing_android/app/build.gradle.kts")
    assert "private fun Process.isAliveCompat()" in process
    assert "private fun Process.waitForCompat(timeoutMillis: Long)" in process
    assert "private fun Process.stopCompat" in process
    assert "Build.VERSION.SDK_INT >= Build.VERSION_CODES.O" in process
    assert "fun isRunning(): Boolean = process?.isAliveCompat() == true" in process
    assert "registration.waitForCompat(75_000L)" in process
    assert "child?.isAliveCompat() != true" in process
    assert "child.stopCompat()" in process
    assert "ignoreWarnings = true" in gradle
    assert "abortOnError = true" in gradle


def test_android_ci_always_uploads_lint_reports() -> None:
    workflow = read(".github/workflows/v1.9.0-rc.13-release.yml")
    assert "Upload Android lint reports" in workflow
    assert "if: always()" in workflow
    assert "android-lint-reports" in workflow
