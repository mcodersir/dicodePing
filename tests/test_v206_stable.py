from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

import pytest

import tools.prepare_vazirmatn as prepare_vazirmatn
from tools.prepare_vazirmatn import _valid_font, _verify_integrity

ROOT = Path(__file__).resolve().parents[1]


def text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_release_metadata_is_prerelease_2_0_6_rc_1() -> None:
    assert 'VERSION = "2.0.6"' in text("dicodeping/constants.py")
    assert 'RELEASE_VERSION = "2.0.6"' in text("dicodeping/constants.py")
    assert '__version__ = "2.0.6"' in text("dicodeping/__init__.py")
    gradle = text("dicodePing_android/app/build.gradle.kts")
    assert 'versionCode = 62' in gradle
    assert 'versionName = "2.0.6"' in gradle
    metadata = text("tools/windows_version_info.txt")
    assert "filevers=(2, 0, 6, 0)" in metadata
    assert "prodvers=(2, 0, 6, 0)" in metadata


def test_desktop_font_is_bundled_and_registered_from_bytes() -> None:
    loader = text("dicodeping/font_loader.py")
    assert "QFontDatabase.addApplicationFontFromData" in loader
    for weight in ("Regular", "Medium", "Bold"):
        assert f"Vazirmatn-{weight}.ttf" in loader
    app = text("app.py")
    assert "app.setFont(choose_persian_font())" in app
    assert 'font-family: "Vazirmatn"' in app


def test_all_desktop_builders_use_prerelease_names_and_vazirmatn() -> None:
    for relative in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = text(relative)
        assert 'APP_VERSION = "2.0.6"' in body
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


def test_prepare_vazirmatn_materializes_all_android_font_files(tmp_path, monkeypatch) -> None:
    payloads = {
        weight: b"\x00\x01\x00\x00" + weight.encode("ascii") + b"x" * 50_000
        for weight in ("Regular", "Medium", "Bold")
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for weight, payload in payloads.items():
            info = tarfile.TarInfo(f"package/fonts/ttf/Vazirmatn-{weight}.ttf")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    package = stream.getvalue()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(package).digest()).decode("ascii")
    tarball_url = "https://example.invalid/vazirmatn.tgz"
    metadata = json.dumps({
        "version": prepare_vazirmatn.VERSION,
        "dist": {"tarball": tarball_url, "integrity": integrity},
    }).encode("utf-8")

    def fake_download(url: str, timeout: float = 35.0, attempts: int = 4) -> bytes:
        del timeout, attempts
        if url == prepare_vazirmatn.REGISTRY:
            return metadata
        if url == tarball_url:
            return package
        raise AssertionError(url)

    monkeypatch.setattr(prepare_vazirmatn, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_vazirmatn, "_download", fake_download)
    prepare_vazirmatn.prepare(android=True)

    android = tmp_path / "dicodePing_android/app/src/main/res/font"
    for weight in ("regular", "medium", "bold"):
        target = android / f"vazirmatn_{weight}.ttf"
        assert target.is_file()
        assert _valid_font(target.read_bytes())
    family = (android / "vazirmatn.xml").read_text(encoding="utf-8")
    assert "@font/vazirmatn_regular" in family
    assert "@font/vazirmatn_medium" in family
    assert "@font/vazirmatn_bold" in family
    assert "xmlns:android" not in family
    assert "android:font" not in family
    assert "app:fontWeight" in family


def test_codeql_materializes_real_bundled_android_fonts_before_gradle() -> None:
    workflow = text(".github/workflows/codeql.yml")
    prepare = "python tools/prepare_vazirmatn.py --android"
    build = "-PdicodePing.codeql=true assembleDebug"
    assert "actions/setup-python@v6" in workflow
    assert 'python-version: "3.12.11"' in workflow
    assert 'assert sys.version_info[:2] == (3, 12)' in workflow
    assert prepare in workflow
    assert workflow.index(prepare) < workflow.index(build)
    assert 'file="dicodePing_android/app/src/main/res/font/vazirmatn_${font}.ttf"' in workflow
    assert 'test -s "$file"' in workflow
    assert "fontProvider" not in workflow


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
    """v2.0.6: SUB is committed as soon as stage 2c finishes; ping + location
    enrichment runs only when the user confirms the post-save modal.
    """
    scanner = text("dicodeping/scanner.py")
    assert "def _recheck_saved_scanner_records" in scanner
    assert "def enrich_saved_scanner_records" in scanner
    assert "enrichment_pending" in scanner
    assert "record.tcp_ms = result.tcp_ms" in scanner
    assert "record.ping_ms = result.ping_ms" in scanner
    assert "force_geo=True" in scanner
    # v2.0.6: desktop probe queue limit was raised so the 28-worker pool
    # stays saturated on heavy scans.
    assert "SCAN_PROBE_QUEUE_LIMIT = min(120," in scanner.replace("\n", "")
    workers = text("dicodeping/workers.py")
    assert "class ScannerEnrichThread" in workers
    ui = text("dicodeping/ui.py")
    assert "def _scanner_offer_enrichment" in ui
    assert "def _scanner_enrich_succeeded" in ui


def test_readme_is_comprehensive_and_professional() -> None:
    """v2.0.6: README must be a comprehensive professional product README."""
    readme = text("README.md")
    assert "## ویژگی‌ها" in readme
    assert "## اسکنر" in readme
    assert "همزمانی واقعی (v2.0.6)" in readme
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
    """v2.0.6: first-launch splash must download sources, ping a 30% sample,
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
    """v2.0.6: desktop service.refresh_sampled must exist. Previously the
    cached-splash path in app.py called a non-existent method and silently
    fell through to the except block, so cached users never got a fresh
    30% sample ping or location refresh at startup.
    """
    service = text("dicodeping/service.py")
    assert "def refresh_sampled" in service


def test_release_is_stable_and_latest() -> None:
    workflow = text(".github/workflows/release.yml")
    assert "workflow_dispatch:" in workflow
    assert "prerelease: false" in workflow
    assert "draft: false" in workflow
    assert "make_latest: true" in workflow
    assert "libxcb-shape0" in workflow


def test_minimal_website_targets_stable_downloads() -> None:
    site = text("docs/site/index.html")
    assert not re.search(r"<(?:img|picture|source)\b", site, re.I)
    assert "2.0.6 پایدار" in site
    assert "releases/download/v2.0.6/" in site
    assert site.count('class="card"') == 6


def test_stable_deployer_is_deterministic_when_packaged() -> None:
    deployer_path = ROOT / "DEPLOY_RELEASE_206_STABLE.bat"
    if not deployer_path.is_file():
        return
    deployer = deployer_path.read_text(encoding="utf-8-sig")
    assert 'set "TAG=v2.0.6"' in deployer
    assert "tools\\validate_v206_stable.py" in deployer
    assert "PUBLISH_HELPER" in deployer
    assert "--verify-existing-only" in deployer
    publisher = text("release-tools/publish_verified_release.py")
    assert '"pr",\n                    "merge"' in publisher
    assert '"workflow",\n                    "run"' in publisher
    assert '"prerelease"' in publisher
    assert '"--log-failed"' in publisher
    assert "webbrowser.open" in publisher
    assert "commits/{head_sha}/check-runs?filter=latest&per_page=100" in publisher
    assert "commits/{head_sha}/statuses?per_page=100" in publisher
    assert "Checks for exact PR head" in publisher
    assert "classify_check_runs" in publisher
    assert "def ensure_advanced_codeql_setup" in publisher
    assert "code-scanning/default-setup" in publisher
    assert '"state=not-configured"' in publisher
    assert "no CodeQL check is skipped" in publisher
    assert "--ensure-codeql-advanced" in deployer
    assert 'for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"' in deployer
    assert 'set "SOURCE_DIR=%~dp0"' not in deployer
    assert "release-tools\\stage_snapshot.py" in deployer
    assert "RELEASE_SOURCE_MANIFEST.sha256" in deployer
    assert "git rm -r -f --ignore-unmatch ." not in deployer
    stage_snapshot = text("release-tools/stage_snapshot.py")
    assert "def prune_destination" in stage_snapshot
    assert "retains their index modes" in stage_snapshot
    assert 'robocopy "%SOURCE_DIR%" "%STAGE_DIR%"' not in deployer
    assert "ghp_" not in deployer

def test_v204_blob_to_config_imported_at_module_level() -> None:
    """v2.0.6: blob_to_config must be imported at module level in scanner.py."""
    scanner = text("dicodeping/scanner.py")
    assert "blob_to_config," in scanner


def test_v204_dark_theme_overrides_all_material3_surface_roles() -> None:
    """v2.0.6: dark theme must override ALL Material3 surface roles so the
    background stays blue-based instead of Material3's default brown."""
    night_colors = text("dicodePing_android/app/src/main/res/values-night/colors.xml")
    assert "m3_surface_variant" in night_colors
    assert "m3_surface_lowest" in night_colors
    assert "m3_surface_high" in night_colors
    theme = text("dicodePing_android/app/src/main/res/values/themes.xml")
    assert "colorSurfaceVariant" in theme
    assert "android:colorBackground" in theme


def test_v204_default_source_has_fallback_urls() -> None:
    """v2.0.6: default source must have jsdelivr CDN fallback URLs so the
    first-launch splash can download even if raw.githubusercontent.com is
    blocked."""
    settings_store = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/SettingsStore.kt")
    assert "DEFAULT_URL_FALLBACK" in settings_store
    assert "defaultSourceUrls" in settings_store
    repo = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "urlsToTry" in repo


def test_v204_scanner_save_overlay_exists_on_all_platforms() -> None:
    """v2.0.6: Telegram-style loading overlay during Stop+Save on all platforms."""
    scanner_layout = text("dicodePing_android/app/src/main/res/layout/fragment_scanner.xml")
    assert "scannerSaveOverlay" in scanner_layout
    scanner_fragment = text("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    assert "scannerSaveOverlay" in scanner_fragment
    desktop_ui = text("dicodeping/ui.py")
    assert "_show_scanner_save_overlay" in desktop_ui
    assert "_hide_scanner_save_overlay" in desktop_ui


def test_v204_scanner_speed_constants_tuned() -> None:
    """v2.0.6: scanner speed constants must be tuned for maximum speed."""
    repo = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "SCANNER_TCP_PROBE_CONCURRENCY = 20" in repo
    assert "SCANNER_TCP_PROBE_TIMEOUT_MS = 600" in repo
    assert "SCANNER_NATIVE_CANDIDATE_LIMIT = 32" in repo
    assert "SCANNER_HEALTHY_TARGET = 32" in repo
    assert "SCANNER_TEST_ATTEMPTS = 1" in repo


def test_v206_universal_apk_includes_armv7() -> None:
    """v2.0.6: the APK must be universal — it must include armeabi-v7a so it
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


def test_v206_tls_bundle_is_packaged_and_verification_stays_enabled() -> None:
    net = text("dicodeping/net.py")
    xray = text("dicodeping/xray.py")
    shared_quality = text("shared/connection_quality.py")
    crawler = text("dicodeping/crawler.py")
    tls12_marker = "minimum_version = ssl.TLSVersion.TLSv1_2"
    assert "ssl.create_default_context" in net
    assert "certifi.where()" in net
    for body in (net, xray, shared_quality, crawler):
        assert "ssl.CERT_NONE" not in body
        assert "check_hostname = False" not in body
        assert tls12_marker in body
    assert "create_tls_context()" in xray
    for relative in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = text(relative)
        assert '"--collect-data"' in body
        assert '"certifi"' in body


def test_v206_normal_ping_and_geo_are_parallel_on_all_clients() -> None:
    desktop = text("dicodeping/rc7_runtime.py")
    assert "def _enrich_records_parallel" in desktop
    assert "ping_future = pool.submit(" in desktop
    assert "geo_future = pool.submit(" in desktop
    assert "_test_records, records" in desktop
    assert "_apply_geo, service" in desktop
    assert "resolve_ips=False" in desktop
    android = text("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    assert "NORMAL_TCP_PROBE_CONCURRENCY = 20" in android
    assert "fun locateAndPing" in android
    assert "val pingJob = async(Dispatchers.IO) { pingServers(input) }" in android
    assert "val geoJob = async(Dispatchers.IO)" in android
    assert "parallelTcpProbe" in android
    ping_probe = text("dicodePing_android/app/src/main/java/ir/dicode/ping/net/PingProbe.kt")
    assert "async" in ping_probe
    assert '"-c", "1"' in ping_probe


def test_v206_android_core_is_not_routed_into_its_own_vpn() -> None:
    service = text("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    assert "addAllowedApplication(packageName)" not in service
    assert ".filter { it.isNotBlank() && it != packageName }" in service
    assert "addDisallowedApplication(packageName)" in service


def test_v206_dead_tcp_endpoints_do_not_spawn_xray() -> None:
    runtime = text("dicodeping/rc7_runtime.py")
    dead_branch = runtime.split("except OSError:", 1)[1].split("probe_outbound_delay", 1)[0]
    assert "return None, None" in dead_branch


def test_v206_macos_packaged_discovery_smoke_is_required() -> None:
    workflow = text(".github/workflows/release.yml")
    macos = workflow.split("  macos:", 1)[1].split("  android:", 1)[0]
    assert "DICODEPING_DISCOVERY_SMOKE=1" in macos
    assert "--discovery-smoke" in macos


def test_v206_uses_requested_apple_connectivity_url_everywhere() -> None:
    url = "http://captive.apple.com/hotspot-detect.html"
    assert url in text("dicodeping/constants.py")
    assert url in text("dicodeping/xray.py")
    assert url in text("shared/connection_quality.py")
    assert url in text("dicodePing_android/app/src/main/java/ir/dicode/ping/xray/CoreBridge.kt")


def test_v206_stable_package_has_no_obsolete_downloadable_font_resources() -> None:
    assert not (ROOT / "dicodePing_android/app/src/main/res/values/font_certs.xml").exists()
    assert not (ROOT / "dicodePing_android/app/src/main/res/values-v26/font_certs.xml").exists()
    prepare = text("tools/prepare_build_workspace.py")
    assert "LEGACY_ANDROID_FONT_RESOURCES" in prepare
    assert "fontProvider" in prepare


def test_codeql_build_skips_only_packaged_native_runtime_verification() -> None:
    """CodeQL compiles Kotlin/Java without building Aether/Usque for every ABI.

    The opt-out must stay explicit and confined to CodeQL. Real APK build and
    release paths must continue to require the verified native helpers.
    """
    gradle = text("dicodePing_android/app/build.gradle.kts")
    codeql = text(".github/workflows/codeql.yml")
    release = text(".github/workflows/release.yml")
    build_apk = text("dicodePing_android/build_apk.sh")
    assert 'gradleProperty("dicodePing.codeql")' in gradle
    assert 'return@doLast' in gradle
    assert '-PdicodePing.codeql=true assembleDebug' in codeql
    assert 'dicodePing.codeql' not in release
    assert 'dicodePing.codeql' not in build_apk
    assert 'python tools/prepare_bundled_cores.py' in build_apk
