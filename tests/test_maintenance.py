from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MaintenanceTests(unittest.TestCase):
    def test_android_rc5_changes_only_release_sequence(self) -> None:
        gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text(encoding="utf-8")
        self.assertIn("versionCode = 8", gradle)
        self.assertIn('versionName = "0.1.3"', gradle)

    def test_windows_startup_owns_preparation(self) -> None:
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        self.assertIn("class StartupPrepareThread", app)
        self.assertIn("startup_prepared=True", app)
        self.assertIn("SERVER_REFRESH_INTERVAL_SECONDS = 2 * 24 * 60 * 60", app)
        after_start = ui.split("def _after_start", 1)[1].split("def apply_theme", 1)[0]
        self.assertNotIn("start_scan(", after_start)
        self.assertNotIn("start_refresh(", after_start)

    def test_windows_protocol_is_not_rendered(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        self.assertNotIn("server.protocol", ui)
        self.assertIn("self.table = QTableWidget(0, 7)", ui)

    def test_android_connection_lock_and_diagnostics(self) -> None:
        servers = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ServersFragment.kt").read_text(encoding="utf-8")
        service = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text(encoding="utf-8")
        manifest = (ROOT / "dicodePing_android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn("server_change_locked", servers)
        self.assertIn("!progress.active && !locked", servers)
        self.assertIn("addDisallowedApplication(packageName)", service)
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
