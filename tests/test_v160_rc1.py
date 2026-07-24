"""Tests for the v1.6.0-rc.1 scanner, volume and quality features."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V160Rc1Tests(unittest.TestCase):
    def test_version_bumped_everywhere(self) -> None:
        constants = (ROOT / "dicodeping/constants.py").read_text(encoding="utf-8")
        init = (ROOT / "dicodeping/__init__.py").read_text(encoding="utf-8")
        windows_builder = (ROOT / "tools/build_windows.py").read_text(encoding="utf-8")
        linux_builder = (ROOT / "tools/build_linux.py").read_text(encoding="utf-8")
        version_info = (ROOT / "tools/windows_version_info.txt").read_text(encoding="utf-8")
        gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text(encoding="utf-8")

        # The 1.6.0 line.  The RC suffix changes per release; we assert
        # the major version is present in every metadata location.
        self.assertIn('VERSION = "1.7.0"', constants)
        self.assertIn('RELEASE_VERSION = "1.7.0-rc.', constants)
        self.assertIn('__version__ = "1.7.0"', init)
        self.assertIn('APP_VERSION = "1.7.0"', windows_builder)
        self.assertIn('APP_VERSION = "1.7.0"', linux_builder)
        self.assertIn('RC_VERSION = "rc.', linux_builder)
        self.assertIn("filevers=(1, 7, 0, 0)", version_info)
        self.assertIn("'ProductVersion', '1.7.0.0'", version_info)
        self.assertIn('versionName = "1.7.0"', gradle)
        self.assertIn('1.7.0-rc.', gradle)

    def test_scanner_module_is_present_and_wired(self) -> None:
        scanner = (ROOT / "dicodeping/scanner.py").read_text(encoding="utf-8")
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")

        # Scanner module exposes the one-click flow.
        self.assertIn("def run_scan(", scanner)
        self.assertIn("SCAN_CRAWL_WORKERS", scanner)
        self.assertIn("SCAN_PROBE_WORKERS", scanner)
        self.assertIn("SCAN_PROBE_TIMEOUT_S", scanner)
        self.assertIn("def generate_sub_name(", scanner)
        self.assertIn("def copy_all_servers(", scanner)
        self.assertIn("def export_subscription(", scanner)
        self.assertIn("def list_scanner_subs(", scanner)

        # ScannerThread is registered in the workers module.
        self.assertIn("class ScannerThread(QThread)", workers)
        self.assertIn("class VolumeFetchThread(QThread)", workers)

        # The UI exposes a dedicated scanner page and copy-all button.
        self.assertIn("def _build_scanner_page", ui)
        self.assertIn("def start_scanner", ui)
        self.assertIn("def scanner_copy_all", ui)
        self.assertIn("def _scanner_succeeded", ui)
        # volume fetch removed in v1.7.0
        # The sidebar now has 5 navigation entries (added scanner).
        self.assertIn('"scanner", "settings", "about"', ui)

    def test_volume_and_quality_modules_are_present(self) -> None:
        # v1.7.0-rc.1: volume detection was removed; only quality rating remains.
        volume = (ROOT / "dicodeping/volume.py").read_text(encoding="utf-8")
        self.assertIn("def rate_quality(", volume)
        self.assertIn("class QualityRating", volume)
        # VolumeAutoDisconnect is kept as a no-op stub for backward compat.
        self.assertIn("class VolumeAutoDisconnect", volume)

    def test_i18n_keys_for_new_features_exist(self) -> None:
        i18n = (ROOT / "dicodeping/i18n.py").read_text(encoding="utf-8")
        for key in (
            "scanner",
            "scanner_run",
            "scanner_running",
            "scanner_bootstrap",
            "scanner_probing",
            "scanner_saving",
            "scanner_done",
            "scanner_result",
            "scanner_copy_all",
            "scanner_copy_base64",
            "scanner_copy_done",
            "scanner_history",
            "scanner_empty_history",
            "volume_unknown",
            "volume_unlimited",
            "volume_consumed",
            "volume_auto_disconnect_title",
            "volume_auto_disconnect_hint",
            "volume_fetch",
            "volume_fetching",
            "quality_excellent",
            "quality_good",
            "quality_fair",
            "quality_poor",
        ):
            self.assertIn(f'"{key}":', i18n, msg=f"Missing i18n key: {key}")

    def test_windows_disconnect_is_defensive(self) -> None:
        xray = (ROOT / "dicodeping/xray.py").read_text(encoding="utf-8")
        # The stop() method must never raise, and TUN cleanup is moved to
        # a background daemon thread so a PowerShell failure cannot crash
        # the GUI on Disconnect.
        self.assertIn("stop() must NEVER raise", xray)
        self.assertIn("target=cleanup_named_tun", xray)
        self.assertIn("daemon=True", xray)
        # The cleanup_named_tun function logs failures instead of raising.
        self.assertIn("TUN cleanup PowerShell invocation failed", xray)

    def test_linux_run_script_is_robust(self) -> None:
        launcher = (ROOT / "packaging/linux/run-dicodePing.sh").read_text(encoding="utf-8")
        # Multiple privilege-escalation strategies must be tried in order.
        self.assertIn("pkexec", launcher)
        self.assertIn("gksudo", launcher)
        self.assertIn("kdesudo", launcher)
        self.assertIn("SUDO_ASKPASS", launcher)
        self.assertIn("sudo -E", launcher)
        # Persian and English error messages for the "all-failed" case.
        self.assertIn("dicodePing راه‌اندازی نشد", launcher)
        self.assertIn("dicodePing could not be launched", launcher)

    def test_linux_bundle_includes_vazirmatn_font(self) -> None:
        # The font files must be present in assets/fonts.
        for name in ("Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf", "Vazirmatn-Medium.ttf"):
            path = ROOT / "assets" / "fonts" / name
            self.assertTrue(path.exists(), msg=f"Missing bundled font: {path}")
            self.assertGreater(path.stat().st_size, 50_000, msg=f"Font {name} is suspiciously small")

        # app.py must register the bundled fonts via QFontDatabase.
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("Vazirmatn-Regular.ttf", app)
        self.assertIn("QFontDatabase.addApplicationFont", app)

        # The Linux builder must ship a .desktop file.
        linux_builder = (ROOT / "tools/build_linux.py").read_text(encoding="utf-8")
        self.assertIn("dicodePing.desktop", linux_builder)
        self.assertIn("app.png", linux_builder)


if __name__ == "__main__":
    unittest.main()
