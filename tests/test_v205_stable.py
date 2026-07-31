from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import pytest

from tools.prepare_vazirmatn import _valid_font, _verify_integrity

ROOT = Path(__file__).resolve().parents[1]


def text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_release_metadata_is_stable_2_0_5() -> None:
    assert 'VERSION = "2.0.5"' in text("dicodeping/constants.py")
    assert 'RELEASE_VERSION = "2.0.5"' in text("dicodeping/constants.py")
    assert '__version__ = "2.0.5"' in text("dicodeping/__init__.py")
    gradle = text("dicodePing_android/app/build.gradle.kts")
    assert 'versionCode = 61' in gradle
    assert 'versionName = "2.0.5"' in gradle
    metadata = text("tools/windows_version_info.txt")
    assert "filevers=(2, 0, 5, 0)" in metadata
    assert "prodvers=(2, 0, 5, 0)" in metadata


def test_desktop_font_is_bundled_and_registered_from_bytes() -> None:
    loader = text("dicodeping/font_loader.py")
    assert "QFontDatabase.addApplicationFontFromData" in loader
    for weight in ("Regular", "Medium", "Bold"):
        assert f"Vazirmatn-{weight}.ttf" in loader
    app = text("app.py")
    assert "app.setFont(choose_persian_font())" in app
    assert 'font-family: "Vazirmatn"' in app


def test_all_desktop_builders_use_stable_names_and_vazirmatn() -> None:
    for relative in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = text(relative)
        assert 'APP_VERSION = "2.0.5"' in body
        assert "RC_VERSION" not in body
        assert 'entrypoint = root / "app_v200.py"' in body
        assert "tools.prepare_vazirmatn" in body
    assert '"--icon"' not in text("tools/build_linux.py")


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


def test_android_uses_gradle_native_packaging_without_manifest_warning() -> None:
    manifest = text("dicodePing_android/app/src/main/AndroidManifest.xml")
    gradle = text("dicodePing_android/app/build.gradle.kts")
    assert "android:extractNativeLibs" not in manifest
    assert "jniLibs.useLegacyPackaging = true" in gradle
    assert "warningsAsErrors = false" in gradle
    assert "ignoreWarnings = false" in gradle
    assert 'lintConfig = file("lint.xml")' in gradle
    assert "enableSplit = false" in gradle
    assert "checkDependencies = true" in gradle


def test_android_apk_font_verification_uses_content_hashes() -> None:
    verifier = text("dicodePing_android/tools/verify_apk_fonts.py")
    assert "hashlib.sha256" in verifier
    assert "archive.read" in verifier
    workflow = text(".github/workflows/release.yml")
    assert 'python tools/verify_apk_fonts.py "$apk"' in workflow
    assert "vazirmatn_${font}" not in workflow
    for script in ("dicodePing_android/build_apk.sh", "dicodePing_android/build_apk.bat"):
        assert "verify_apk_fonts.py" in text(script)
        assert "warning-mode=fail" in text(script)
        assert "lintStandardRelease" in text(script)


def test_scanner_splits_save_from_optional_enrichment() -> None:
    """v2.0.5: SUB is committed as soon as stage 2c finishes; ping + location
    enrichment runs only when the user confirms the post-save modal.
    """
    scanner = text("dicodeping/scanner.py")
    assert "def _recheck_saved_scanner_records" in scanner
    assert "def enrich_saved_scanner_records" in scanner
    assert "enrichment_pending" in scanner
    assert "record.tcp_ms = result.tcp_ms" in scanner
    assert "record.ping_ms = result.ping_ms" in scanner
    assert "force_geo=True" in scanner
    # v2.0.5: desktop probe queue limit was raised so the 28-worker pool
    # stays saturated on heavy scans.
    assert "SCAN_PROBE_QUEUE_LIMIT = min(120," in scanner.replace("\n", "")
    workers = text("dicodeping/workers.py")
    assert "class ScannerEnrichThread" in workers
    ui = text("dicodeping/ui.py")
    assert "def _scanner_offer_enrichment" in ui
    assert "def _scanner_enrich_succeeded" in ui


def test_readme_is_comprehensive_and_professional() -> None:
    """v2.0.5: README must be a comprehensive professional product README."""
    readme = text("README.md")
    assert "## ویژگی‌ها" in readme
    assert "## اسکنر" in readme
    assert "همزمانی واقعی (v2.0.5)" in readme
    assert "parallelTcpProbe" in readme or "parallel TCP" in readme
    assert "## عیب‌یابی" in readme
    assert "## مجوز" in readme
    assert "SBOM" in readme
    assert len(readme) > 5000


def test_android_scanner_runs_probes_concurrently_and_offers_enrichment_modal() -> None:
    repository = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "SCANNER_TCP_PROBE_CONCURRENCY = 20" in repository
    assert "SCANNER_TCP_PROBE_TIMEOUT_MS = 600" in repository
    assert "SCANNER_NATIVE_CANDIDATE_LIMIT = 32" in repository
    assert "fun parallelTcpProbe" in repository
    assert "fun enrichScannerRecords" in repository
    assert '"post_save_verify"' in repository
    assert "forceGeoRefresh = true" in repository
    coordinator = text("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    assert "ScannerStage.ENRICHING" in coordinator
    assert "ScannerStage.ENRICHED" in coordinator
    assert "fun enrichSavedRecords" in coordinator
    assert "enrichmentPending" in coordinator
    fragment = text("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    assert "showEnrichmentModal" in fragment
    assert "MaterialAlertDialogBuilder" in fragment


def test_first_launch_splash_fetches_pings_and_resolves_geo_inline() -> None:
    """v2.0.5: first-launch splash must download sources, ping a 30% sample,
    AND resolve geo on that sample before openMain. Previously geo was
    deferred to finishStartupInBackground which only ran after openMain
    and was capped at 48 rows, so first-launch users saw no flags.
    """
    repo = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "firstRun" in repo
    assert "locateServers(sample" in repo
    splash = text("dicodePing_android/app/src/main/java/ir/dicode/ping/SplashActivity.kt")
    assert "FIRST_RUN_STARTUP_TIMEOUT_MS" in splash
    assert "firstRun" in splash
    assert "splash_resolving_locations" in splash
    strings_en = text("dicodePing_android/app/src/main/res/values/strings.xml")
    strings_fa = text("dicodePing_android/app/src/main/res/values-fa/strings.xml")
    assert "splash_resolving_locations" in strings_en
    assert "splash_resolving_locations" in strings_fa


def test_desktop_refresh_sampled_method_exists() -> None:
    """v2.0.5: desktop service.refresh_sampled must exist. Previously the
    cached-splash path in app.py called a non-existent method and silently
    fell through to the except block, so cached users never got a fresh
    30% sample ping or location refresh at startup.
    """
    service = text("dicodeping/service.py")
    assert "def refresh_sampled" in service


def test_stable_release_is_latest_not_prerelease() -> None:
    workflow = text(".github/workflows/release.yml")
    assert "workflow_dispatch:" in workflow
    assert "prerelease: false" in workflow
    assert "draft: false" in workflow
    assert "make_latest: true" in workflow
    assert "libxcb-shape0" in workflow
    waiter = text("tools/wait_for_github_release.ps1")
    assert "event=push" not in waiter
    assert "$release.prerelease -eq $false" in waiter
    assert "$latest.tag_name -eq $Tag" in waiter


def test_minimal_website_targets_stable_downloads() -> None:
    site = text("docs/site/index.html")
    assert not re.search(r"<(?:img|picture|source)\b", site, re.I)
    assert "2.0.5 پایدار" in site
    assert "releases/download/v2.0.5/" in site
    assert site.count('class="card"') == 6


def test_stable_deployer_is_deterministic_and_pages_required() -> None:
    deployer = text("DEPLOY_RELEASE_200.bat")
    assert 'set "TAG=v2.0.5"' in deployer
    assert "publish_release_trigger.ps1" in deployer
    assert "MaxAttempts 8" in deployer
    assert "goto :pages_failed" in deployer
    assert "tools\\validate_v205_stable.py" in deployer


def test_v204_blob_to_config_imported_at_module_level() -> None:
    """v2.0.5: blob_to_config must be imported at module level in scanner.py."""
    scanner = text("dicodeping/scanner.py")
    assert "blob_to_config," in scanner


def test_v204_dark_theme_overrides_all_material3_surface_roles() -> None:
    """v2.0.5: dark theme must override ALL Material3 surface roles so the
    background stays blue-based instead of Material3's default brown."""
    night_colors = text("dicodePing_android/app/src/main/res/values-night/colors.xml")
    assert "m3_surface_variant" in night_colors
    assert "m3_surface_lowest" in night_colors
    assert "m3_surface_high" in night_colors
    theme = text("dicodePing_android/app/src/main/res/values/themes.xml")
    assert "colorSurfaceVariant" in theme
    assert "android:colorBackground" in theme


def test_v204_default_source_has_fallback_urls() -> None:
    """v2.0.5: default source must have jsdelivr CDN fallback URLs so the
    first-launch splash can download even if raw.githubusercontent.com is
    blocked."""
    settings_store = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/SettingsStore.kt")
    assert "DEFAULT_URL_FALLBACK" in settings_store
    assert "defaultSourceUrls" in settings_store
    repo = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "urlsToTry" in repo


def test_v204_scanner_save_overlay_exists_on_all_platforms() -> None:
    """v2.0.5: Telegram-style loading overlay during Stop+Save on all platforms."""
    scanner_layout = text("dicodePing_android/app/src/main/res/layout/fragment_scanner.xml")
    assert "scannerSaveOverlay" in scanner_layout
    scanner_fragment = text("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    assert "scannerSaveOverlay" in scanner_fragment
    desktop_ui = text("dicodeping/ui.py")
    assert "_show_scanner_save_overlay" in desktop_ui
    assert "_hide_scanner_save_overlay" in desktop_ui


def test_v204_scanner_speed_constants_tuned() -> None:
    """v2.0.5: scanner speed constants must be tuned for maximum speed."""
    repo = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "SCANNER_TCP_PROBE_CONCURRENCY = 20" in repo
    assert "SCANNER_TCP_PROBE_TIMEOUT_MS = 600" in repo
    assert "SCANNER_NATIVE_CANDIDATE_LIMIT = 32" in repo
    assert "SCANNER_HEALTHY_TARGET = 32" in repo
    assert "SCANNER_TEST_ATTEMPTS = 1" in repo


def test_v205_universal_apk_includes_armv7() -> None:
    """v2.0.5: the APK must be universal — it must include armeabi-v7a so it
    installs on older 32-bit ARM devices (arm-v7a). Previously only
    arm64-v8a and x86_64 were packaged, which made the APK show as
    incompatible on 32-bit ARM phones."""
    gradle = text("dicodePing_android/app/build.gradle.kts")
    assert 'setOf("arm64-v8a", "armeabi-v7a", "x86_64")' in gradle
    assert '"armeabi-v7a" to 40' in gradle
    verify_cores = text("dicodePing_android/tools/verify_apk_cores.py")
    assert '"armeabi-v7a": 40' in verify_cores
    prepare_cores = text("dicodePing_android/tools/prepare_bundled_cores.py")
    assert '"armeabi-v7a"' in prepare_cores
    assert "armv7-linux-androideabi" in prepare_cores
    release_wf = text(".github/workflows/release.yml")
    assert "armv7-linux-androideabi" in release_wf
    assert "for abi in arm64-v8a armeabi-v7a x86_64" in release_wf
