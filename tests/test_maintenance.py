from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MaintenanceTests(unittest.TestCase):
    def test_android_rc9_release_sequence_and_pipeline(self) -> None:
        gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text(encoding="utf-8")
        repository = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt").read_text(encoding="utf-8")
        adapter = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ServerAdapter.kt").read_text(encoding="utf-8")
        self.assertIn("versionCode = 21", gradle)
        self.assertIn('versionName = "0.1.5"', gradle)
        refresh = repository.split("fun refreshAll()", 1)[1].split("private suspend fun refreshServersInternal", 1)[0]
        self.assertLess(refresh.index("refreshServersInternal()"), refresh.index("locateServers("))
        self.assertLess(refresh.index("locateServers("), refresh.index("pingServers("))
        self.assertIn("REAL_PROBE_CONCURRENCY = 12", repository)
        self.assertIn("RETRY_PROBE_CONCURRENCY = 6", repository)
        self.assertIn("testState = ServerRecord.TEST_RUNNING", repository)
        self.assertIn("Animation.INFINITE", adapter)

    def test_desktop_workers_cancel_cooperatively(self) -> None:
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
        runtime = (ROOT / "dicodeping/rc6_runtime.py").read_text(encoding="utf-8")
        self.assertIn("class TaskCancelled", workers)
        self.assertIn("self.isInterruptionRequested()", workers)
        self.assertIn("event.ignore()", runtime)
        self.assertIn("worker.finished.connect", runtime)

    def test_windows_startup_owns_preparation(self) -> None:
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        self.assertIn("class StartupPrepareThread", app)
        self.assertIn("startup_prepared=True", app)
        self.assertIn("SERVER_REFRESH_INTERVAL_SECONDS = 2 * 24 * 60 * 60", app)
        after_start = ui.split("def _after_start", 1)[1].split("def apply_theme", 1)[0]
        self.assertNotIn("start_scan(", after_start)
        self.assertNotIn("start_refresh(", after_start)

    def test_application_update_is_checked_before_subscription_revisions(self) -> None:
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        workers = (ROOT / "dicodeping" / "workers.py").read_text(encoding="utf-8")
        app_run = app.split("class UpdateCheckThread", 1)[1].split("_SINGLE_INSTANCE_HANDLE", 1)[0]
        worker_run = workers.split("class ApplicationUpdateThread", 1)[1].split("def _flush_windows_dns", 1)[0]
        self.assertLess(app_run.index("find_application_update"), app_run.index("check_source_updates"))
        self.assertLess(worker_run.index("find_application_update"), worker_run.index("check_source_updates"))

    def test_splash_tracks_real_server_discovery_and_logs_are_visible(self) -> None:
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        self.assertIn("startup_scan.preview_ready.connect", app)
        self.assertIn("Fetching and preparing servers", app)
        self.assertIn('window.settings.get("auto_scan_empty", True)', app)
        self.assertIn("QTimer.singleShot(12000, splash.close)", app)
        self.assertIn("self.log_path_label = QLabel(str(LOG_FILE))", ui)
        self.assertIn("QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE)))", ui)

    def test_rc9_startup_cannot_be_held_by_network_or_ui_failure(self) -> None:
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        startup_worker = app.split("class StartupPrepareThread", 1)[1].split("_SINGLE_INSTANCE_HANDLE", 1)[0]
        self.assertNotIn("discover_config_entries", startup_worker)
        self.assertNotIn("ServerService", startup_worker)
        self.assertIn("StartupGate()", app)
        self.assertIn("watchdog.setInterval(4000)", app)
        self.assertIn("preloaded_servers=[]", app)
        self.assertIn("finally:", app)
        self.assertIn("splash.close()", app)
        self.assertIn("--startup-smoke-test", app)

    def test_rc9_filter_callbacks_do_not_bind_a_runtime_patched_method(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        self.assertIn("textChanged.connect(lambda _text: self.render_servers())", ui)
        self.assertIn("currentIndexChanged.connect(lambda _index: self.render_servers())", ui)
        self.assertNotIn("textChanged.connect(self.render_servers)", ui)

    def test_rc9_resize_filter_is_scoped_to_the_main_window(self) -> None:
        runtime = (ROOT / "dicodeping/rc7_runtime.py").read_text(encoding="utf-8")
        self.assertIn("self.installEventFilter(self)", runtime)
        self.assertIn("self.removeEventFilter(self)", runtime)
        self.assertNotIn("QApplication.instance().installEventFilter(self)", runtime)
        self.assertIn("obj is not self", runtime)

    def test_rc9_packaged_desktop_smoke_tests_require_success(self) -> None:
        windows = (ROOT / ".github/workflows/v013-windows-build.yml").read_text(encoding="utf-8")
        linux = (ROOT / ".github/workflows/v013-linux-rc5-build.yml").read_text(encoding="utf-8")
        self.assertIn("--startup-smoke-test", windows)
        self.assertIn("--startup-smoke-test", linux)
        self.assertIn("DICODEPING_STARTUP_SMOKE_REPORT", windows)
        self.assertIn("DICODEPING_STARTUP_SMOKE_REPORT", linux)
        self.assertIn("Start-Process", windows)
        self.assertNotIn('test "$status" -eq 124', linux)

    def test_rc2_release_tests_packaged_discovery_and_rendering(self) -> None:
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/v014-rc1-release.yml").read_text(encoding="utf-8")
        self.assertIn("DICODEPING_DISCOVERY_SMOKE", app)
        self.assertIn("preview_only=True", app)
        self.assertIn("rendered_rows", app)
        self.assertEqual(workflow.count("DICODEPING_DISCOVERY_SMOKE"), 2)
        self.assertIn("dicodePing-v0.1.5-rc.2-windows.exe", workflow)
        self.assertIn("dicodePing-v0.1.5-rc.2-linux-x86_64.tar.gz", workflow)

    def test_windows_protocol_is_not_rendered(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        self.assertNotIn("server.protocol", ui)
        self.assertIn("self.table = QTableWidget(0, 7)", ui)

    def test_rc8_desktop_bug_fixes_are_wired(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        rc7 = (ROOT / "dicodeping/rc7_runtime.py").read_text(encoding="utf-8")
        rc8 = (ROOT / "dicodeping/rc8_runtime.py").read_text(encoding="utf-8")
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")

        self.assertIn("self.table.blockSignals(True)", ui)
        self.assertIn("self._worker_finished(worker)", ui)
        self.assertIn("full = label.text()", rc7)
        self.assertIn("geo_lookup_ips(records)", rc7)
        self.assertIn("QHeaderView.Fixed", rc8)
        self.assertIn("self.table.viewport().width()", rc8)
        self.assertIn("waits = (0.25, 0.7)", workers)
        self.assertIn("allow_system_proxy=False", workers)

    def test_android_connection_lock_and_diagnostics(self) -> None:
        servers = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ServersFragment.kt").read_text(encoding="utf-8")
        service = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text(encoding="utf-8")
        manifest = (ROOT / "dicodePing_android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn("server_change_locked", servers)
        self.assertIn("canConnectSelected(locked)", servers)
        self.assertIn("!ServerPolicy.isRestricted(selected)", servers)
        self.assertIn("addDisallowedApplication(packageName)", service)
        self.assertIn("@Synchronized", service)
        self.assertIn("androidx.core.content.FileProvider", manifest)

    def test_android_uses_single_branded_custom_splash(self) -> None:
        theme = (ROOT / "dicodePing_android/app/src/main/res/values-v31/themes.xml").read_text(encoding="utf-8")
        splash = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/SplashActivity.kt").read_text(encoding="utf-8")
        self.assertIn("ic_splash_transparent", theme)
        self.assertIn("repo.initialize()", splash)

    def test_android_splash_theme_has_no_missing_androidx_attribute(self) -> None:
        theme = (ROOT / "dicodePing_android/app/src/main/res/values-v31/themes.xml").read_text(encoding="utf-8")
        self.assertNotIn("postSplashScreenTheme", theme)
        self.assertIn("android:windowSplashScreenBackground", theme)

    def test_connection_stability_tuning_is_present(self) -> None:
        android_service = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text(encoding="utf-8")
        android_config = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/xray/XrayConfigBuilder.kt").read_text(encoding="utf-8")
        windows_config = (ROOT / "dicodeping/xray.py").read_text(encoding="utf-8")
        self.assertIn("START_REDELIVER_INTENT", android_service)
        self.assertIn("VPN_MTU = 1400", android_service)
        self.assertIn("happyEyeballs", android_config)
        self.assertIn("tcpKeepAliveInterval", windows_config)

    def test_android_ipv6_is_fail_closed_inside_the_vpn(self) -> None:
        service = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text(encoding="utf-8")
        config = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/xray/XrayConfigBuilder.kt").read_text(encoding="utf-8")

        self.assertIn('.addAddress(VPN_IPV6_ADDRESS, VPN_IPV6_PREFIX_LENGTH)', service)
        self.assertIn('.addRoute("::", 0)', service)
        self.assertIn('VPN_IPV6_ADDRESS = "fdfe:dcba:9876::1"', service)
        self.assertIn('"fc00::/7"', config)
        self.assertIn('"fe80::/10"', config)

    def test_windows_taskbar_icon_is_applied_at_all_shell_layers(self) -> None:
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        integration = (ROOT / "dicodeping/windows_integration.py").read_text(encoding="utf-8")
        spec = (ROOT / "dicodePing.spec").read_text(encoding="utf-8")

        self.assertIn("app.setWindowIcon(application_icon)", app)
        self.assertIn("set_process_app_user_model_id(APP_ID)", app)
        self.assertIn("apply_native_window_icon(window", app)
        self.assertLess(app.index("set_app_id()"), app.index("app = QApplication"))
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", integration)
        self.assertIn("WM_SETICON", integration.upper())
        self.assertIn('icon=str(assets / "app.ico")', spec)
        self.assertIn('version=str(root / "tools" / "windows_version_info.txt")', spec)

    def test_windows_icon_contains_multiple_resolutions(self) -> None:
        import struct

        data = (ROOT / "assets" / "app.ico").read_bytes()
        reserved, image_type, count = struct.unpack_from("<HHH", data, 0)
        self.assertEqual((reserved, image_type), (0, 1))
        self.assertGreaterEqual(count, 4)
        sizes = set()
        for index in range(count):
            width, height = struct.unpack_from("BB", data, 6 + index * 16)
            sizes.add((256 if width == 0 else width, 256 if height == 0 else height))
        self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(sizes))

    def test_source_repository_does_not_track_native_release_artifacts(self) -> None:
        import subprocess

        tracked = set(
            subprocess.check_output(
                ["git", "-C", str(ROOT), "ls-files"],
                text=True,
                encoding="utf-8",
            ).splitlines()
        )
        forbidden = {
            "core/xray.exe",
            "core/xray",
            "core/wintun.dll",
            "core/geoip.dat",
            "core/geosite.dat",
        }
        self.assertFalse(tracked & forbidden)
        self.assertFalse({path for path in tracked if path.lower().endswith(".aar")})


if __name__ == "__main__":
    unittest.main()
