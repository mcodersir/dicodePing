from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import pytest

from tools.prepare_vazirmatn import _valid_font, _verify_integrity

ROOT = Path(__file__).resolve().parents[1]


def text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_release_metadata_is_2_0_rc1() -> None:
    assert 'VERSION = "2.0.0"' in text("dicodeping/constants.py")
    assert 'RELEASE_VERSION = "2.0.0-rc.1"' in text("dicodeping/constants.py")
    assert '__version__ = "2.0.0rc1"' in text("dicodeping/__init__.py")
    gradle = text("dicodePing_android/app/build.gradle.kts")
    assert 'versionCode = 55' in gradle
    assert 'versionName = "2.0.0-rc.1"' in gradle
    metadata = text("tools/windows_version_info.txt")
    assert "filevers=(2, 0, 0, 1)" in metadata
    assert "prodvers=(2, 0, 0, 1)" in metadata


def test_desktop_font_is_bundled_and_registered_from_bytes() -> None:
    loader = text("dicodeping/font_loader.py")
    assert "QFontDatabase.addApplicationFontFromData" in loader
    assert "Vazirmatn-Regular.ttf" in loader
    assert "Vazirmatn-Medium.ttf" in loader
    assert "Vazirmatn-Bold.ttf" in loader
    assert "if IS_FROZEN:" in loader
    app = text("app.py")
    assert "app.setFont(choose_persian_font())" in app
    assert 'font-family: "Vazirmatn"' in app


def test_all_desktop_builders_fetch_and_require_vazirmatn() -> None:
    for relative in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = text(relative)
        assert "tools.prepare_vazirmatn" in body
        assert 'entrypoint = root / "app_v200_rc1.py"' in body
        assert 'Vazirmatn-' in body


def test_font_integrity_check_accepts_exact_sha512_and_rejects_changes() -> None:
    payload = b"font-package-content"
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
    _verify_integrity(payload, integrity)
    with pytest.raises(RuntimeError):
        _verify_integrity(payload + b"changed", integrity)


def test_font_header_validation() -> None:
    assert _valid_font(b"\x00\x01\x00\x00" + b"x" * 50_000)
    assert _valid_font(b"OTTO" + b"x" * 50_000)
    assert not _valid_font(b"fake" + b"x" * 50_000)
    assert not _valid_font(b"OTTO" + b"x" * 100)


def test_android_uses_local_bundled_font_not_downloadable_provider() -> None:
    family = text("dicodePing_android/app/src/main/res/font/vazirmatn.xml")
    assert "fontProvider" not in family
    for weight in ("regular", "medium", "bold"):
        assert f"@font/vazirmatn_{weight}" in family
    assert "prepare_vazirmatn.py --android" in text("dicodePing_android/build_apk.sh")
    assert "prepare_vazirmatn.py --android" in text("dicodePing_android/build_apk.bat")


def test_source_snapshot_does_not_ship_generated_font_files() -> None:
    assert not list(ROOT.glob("assets/fonts/*.ttf"))
    assert not list(ROOT.glob("dicodePing_android/app/src/main/res/font/vazirmatn_*.ttf"))


def test_desktop_scanner_rechecks_saved_sub_ping_and_location() -> None:
    scanner = text("dicodeping/scanner.py")
    assert "def _recheck_saved_scanner_records" in scanner
    assert "test_config," in scanner
    assert "record.tcp_ms = result.tcp_ms" in scanner
    assert "record.ping_ms = result.ping_ms" in scanner
    assert "force_geo=True" in scanner
    assert 'history_record["post_save_verified_at"]' in scanner


def test_android_scanner_rechecks_saved_sub_and_location() -> None:
    repository = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert '"post_save_verify"' in repository
    assert "proxyProbe.measureOutboundDelay" in repository
    assert "forceGeoRefresh = true" in repository
    assert '.put("postSaveVerified", true)' in repository


def test_minimal_website_has_no_screenshots_and_all_downloads() -> None:
    site = text("docs/site/index.html")
    assert not re.search(r"<(?:img|picture|source)\b", site, re.I)
    assert "screenshot" not in site.casefold()
    assert site.count('class="card"') == 6
    for asset in (
        "windows-x64.exe", "linux-x86_64.tar.gz", "macos-arm64.dmg",
        "macos-x86_64.dmg", "android.apk", "source.zip",
    ):
        assert asset in site


def test_packaged_smoke_reports_resolved_font_family() -> None:
    app = text("app.py")
    assert app.count("font_family={app.font().family()}") >= 3
    workflow = text(".github/workflows/release.yml")
    assert workflow.count("font_family=Vazirmatn") >= 3


def test_ui_minimalization_is_shared_across_desktop_and_android() -> None:
    desktop = text("dicodeping/ui.py")
    assert "border-radius: 16px" in desktop
    android = text("dicodePing_android/app/src/main/res/values/themes.xml")
    assert "cardCornerRadius\">20dp" in android
    assert "strokeWidth\">0dp" in android
    assert "android:minHeight\">46dp" in android


def test_release_deployer_survives_transient_github_https_failure() -> None:
    deployer = text("DEPLOY_PRERELEASE_200_RC1.bat")
    trigger = text("tools/publish_release_trigger.ps1")
    assert "call :push_main_with_retry" in deployer
    assert "for /L %%A in (1,1,8)" in deployer
    assert "publish_release_trigger.ps1" in deployer
    assert "MaxAttempts 8" in deployer
    assert "Invoke-GhRetry" in trigger
    assert "repos/$Repository/commits/$CommitSha" in trigger
    assert "repos/$Repository/git/refs" in trigger
    assert '"workflow", "run", $WorkflowFile' in trigger
    assert '"--ref", $Tag' in trigger
    assert "Remote tag verification failed" in trigger
