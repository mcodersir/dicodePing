from __future__ import annotations

from pathlib import Path
from unittest import mock

from dicodeping.config_checker import test_config as run_quality_test


ROOT = Path(__file__).resolve().parents[1]
VALID = "vless://00000000-0000-0000-0000-000000000000@example.com:443?security=tls#node"


def read(path: str) -> str:
    return (ROOT / path).read_text("utf-8")


def test_real_checker_requires_repeated_data_plane_success_and_uses_median() -> None:
    with mock.patch("dicodeping.config_checker.build_xray_outbound", return_value={"protocol": "vless"}), \
         mock.patch("dicodeping.config_checker.probe_outbound_delay", side_effect=[140, None, 100]):
        result = run_quality_test(VALID, attempts=3, min_success=2, attempt_gap_seconds=0)
    assert result.ok
    assert result.tester == "xray-http"
    assert result.success_count == 2
    assert result.samples_ms == (140, 100)
    assert result.ping_ms == 120
    assert result.min_ms == 100


def test_scanner_is_wired_to_dicode_config_checker_quality_results() -> None:
    scanner = read("dicodeping/scanner.py")
    checker = read("dicodeping/config_checker.py")
    assert "from .config_checker import ConfigQualityResult, test_config" in scanner
    assert "engine=DicodeConfigChecker" in scanner
    assert "median=" in scanner and "samples=" in scanner
    assert "probe_outbound_delay" in checker
    assert 'tester = "xray-http" if full_tunnel_supported else "tcp-fallback"' in checker


def test_desktop_startup_finishes_updates_testing_and_geo_before_main_window() -> None:
    app = read("app.py")
    worker = app.split("class StartupPrepareThread", 1)[1].split("class UpdateCheckThread", 1)[0]
    assert worker.index("find_application_update") < worker.index("check_source_updates")
    assert worker.index("discover_config_entries") < worker.index("build_and_save")
    assert "ping_progress=ping_progress" in worker
    assert "geo_progress=geo_progress" in worker
    prepared = app.split("def prepared(", 1)[1].split("def preparation_timed_out", 1)[0]
    assert "window = MainWindow(" in prepared
    assert "worker.ready.connect(prepared)" in app


def test_android_startup_and_scanner_use_full_pre_ui_and_repeated_native_probes() -> None:
    splash = read("dicodePing_android/app/src/main/java/ir/dicode/ping/SplashActivity.kt")
    repository = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "repo.initialize()" in splash
    assert "repo.subscriptionUpdates()" in splash
    assert "repo.refreshAllAndWait()" in splash
    assert "SCANNER_TEST_ATTEMPTS = 3" in repository
    assert "SCANNER_MIN_SUCCESS = 2" in repository
    assert "?.sorted()" in repository
    assert 'tester=xray-http' in repository


def test_rc6_sidebar_and_live_scanner_log_views_are_directional_and_separate() -> None:
    ui = read("dicodeping/ui.py")
    assert "QToolButton.ToolButtonPopupMode" not in ui
    assert "Qt.RightToLeft if self.window.is_rtl else Qt.LeftToRight" in ui
    assert "Qt.ToolButtonTextBesideIcon" in ui
    assert "self.scanner_tg_log_view" in ui
    assert "self.scanner_test_log_view" in ui
    assert 'if "[TG]" in line' in ui
    assert '("[TEST]", "[DISCONNECT]")' in ui


def test_rc6_release_is_bilingual_and_multi_platform() -> None:
    notes = read("docs/releases/v1.9.0-rc.6.md")
    workflow = read(".github/workflows/v1.9.0-rc.6-release.yml")
    deploy = read("DEPLOY_PRERELEASE_RC6.bat")
    assert "## فارسی" in notes and "## English" in notes
    for asset in ("windows-x64.exe", "linux-x86_64.tar.gz", "android.apk"):
        assert asset in workflow
    assert "macos-${{ matrix.architecture }}.dmg" in workflow
    assert "architecture: arm64" in workflow
    assert "architecture: x86_64" in workflow
    assert "v1.9.0-rc.6" in deploy
    assert "wait_for_github_release_rc6.ps1" in deploy
