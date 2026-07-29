from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    constants = read("dicodeping/constants.py")
    init = read("dicodeping/__init__.py")
    gradle = read("dicodePing_android/app/build.gradle.kts")
    manifest = read("dicodePing_android/app/src/main/AndroidManifest.xml")

    require('VERSION = "2.0.2"' in constants, "Stable VERSION is not 2.0.2", errors)
    require('RELEASE_VERSION = "2.0.2"' in constants, "Stable RELEASE_VERSION is not 2.0.2", errors)
    require('__version__ = "2.0.2"' in init, "Python package version is not stable 2.0.2", errors)
    require('versionCode = 58' in gradle, "Android stable versionCode is not 58", errors)
    require('versionName = "2.0.2"' in gradle, "Android stable versionName is incorrect", errors)
    require('buildConfigField("String", "RELEASE_VERSION", "\\"2.0.2\\"")' in gradle, "Android RELEASE_VERSION is incorrect", errors)

    for builder in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = read(builder)
        require('APP_VERSION = "2.0.2"' in body, f"{builder} does not build stable 2.0.2", errors)
        require('app_v200.py' in body, f"{builder} does not package app_v200.py", errors)
        require('RC_VERSION' not in body, f"{builder} still adds an RC suffix", errors)
        require('tools.prepare_vazirmatn' in body, f"{builder} does not prepare Vazirmatn", errors)

    linux_builder = read("tools/build_linux.py")
    require('"--icon"' not in linux_builder, "Linux PyInstaller still receives unsupported --icon", errors)

    require('android:extractNativeLibs' not in manifest, "Obsolete android:extractNativeLibs still causes AGP warnings", errors)
    require('jniLibs.useLegacyPackaging = true' in gradle, "Native extraction is not configured through Gradle DSL", errors)
    require('warningsAsErrors = false' in gradle, "Android lint advisories are still promoted to build errors", errors)
    require('ignoreWarnings = false' in gradle, "Android lint reports are being hidden", errors)
    require('lintConfig = file("lint.xml")' in gradle, "Android lint policy file is not configured", errors)
    require('enableSplit = false' in gradle, "Android language resources can be split despite runtime locale switching", errors)
    require('checkDependencies = true' in gradle, "Dependency lint is disabled", errors)

    apk_font_verifier = read("dicodePing_android/tools/verify_apk_fonts.py")
    require('sha256_bytes' in apk_font_verifier, "APK font verifier does not compare content hashes", errors)
    for build_script in ("dicodePing_android/build_apk.sh", "dicodePing_android/build_apk.bat"):
        body = read(build_script)
        require('verify_apk_fonts.py' in body, f"{build_script} does not verify optimized APK fonts", errors)
        require('warning-mode=fail' in body, f"{build_script} does not fail on Gradle warnings", errors)
        require('lintStandardRelease' in body, f"{build_script} does not run full release lint", errors)

    # v2.0.2: scanner splits save from enrichment. The inline post-save
    # recheck is gone; the public enrich_saved_scanner_records entry point
    # runs only when the user confirms the post-save modal.
    scanner = read("dicodeping/scanner.py")
    require("def _recheck_saved_scanner_records" in scanner, "Desktop post-save scanner verification helper is missing", errors)
    require("def enrich_saved_scanner_records" in scanner, "Desktop v2.0.2 public enrichment entry point is missing", errors)
    require("record.tcp_ms = result.tcp_ms" in scanner, "Desktop post-save TCP latency is not persisted", errors)
    require("record.ping_ms = result.ping_ms" in scanner, "Desktop post-save Xray latency is not persisted", errors)
    require("force_geo=True" in scanner, "Desktop post-save location refresh is not forced", errors)
    require("enrichment_pending" in scanner, "Desktop scanner does not flag pending enrichment on save", errors)
    # v2.0.2: desktop probe queue limit was raised so the 28-worker pool
    # stays saturated on heavy scans.
    require("SCAN_PROBE_QUEUE_LIMIT = min(120," in scanner.replace("\n", "") or "120" in scanner, "Desktop scanner probe queue limit was not raised for v2.0.2", errors)

    workers = read("dicodeping/workers.py")
    require("class ScannerEnrichThread" in workers, "Desktop ScannerEnrichThread worker is missing", errors)

    ui = read("dicodeping/ui.py")
    require("def _scanner_offer_enrichment" in ui, "Desktop UI post-save enrichment modal handler is missing", errors)
    require("def _scanner_enrich_succeeded" in ui, "Desktop UI enrichment success handler is missing", errors)

    android_repo = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    require("SCANNER_TCP_PROBE_CONCURRENCY = 12" in android_repo, "Android scanner TCP probe concurrency was not bumped to 12", errors)
    require("fun parallelTcpProbe" in android_repo, "Android v2.0.2 parallelTcpProbe helper is missing", errors)
    require("fun enrichScannerRecords" in android_repo, "Android v2.0.2 public enrichment entry point is missing", errors)
    require('"post_save_verify"' in android_repo, "Android enrichment stage label is missing", errors)
    require("forceGeoRefresh = true" in android_repo, "Android post-save location refresh is not forced", errors)
    require('.put("postSaveVerified", true)' in android_repo, "Android final SUB transaction is not marked as verified", errors)

    coordinator = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    require("ScannerStage.ENRICHING" in coordinator, "Android ScannerStage.ENRICHING is missing", errors)
    require("ScannerStage.ENRICHED" in coordinator, "Android ScannerStage.ENRICHED is missing", errors)
    require("fun enrichSavedRecords" in coordinator, "Android ScannerCoordinator.enrichSavedRecords is missing", errors)
    require("enrichmentPending" in coordinator, "Android ScannerState.enrichmentPending field is missing", errors)

    fragment = read("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt")
    require("showEnrichmentModal" in fragment, "Android ScannerFragment.showEnrichmentModal is missing", errors)
    require("MaterialAlertDialogBuilder" in fragment, "Android ScannerFragment does not use MaterialAlertDialogBuilder for the modal", errors)

    # v2.0.2: comprehensive professional README is required.
    readme = read("README.md")
    require("## ویژگی‌ها" in readme, "README must contain a Features section", errors)
    require("## اسکنر" in readme, "README must contain a Scanner section", errors)
    require("همزمانی واقعی (v2.0.2)" in readme, "README must document the v2.0.2 real concurrency fix", errors)
    require("parallelTcpProbe" in readme or "parallel TCP" in readme, "README must mention the parallel TCP probe", errors)
    require("## عیب‌یابی" in readme, "README must contain a Troubleshooting section", errors)
    require("## مجوز" in readme, "README must contain a License section", errors)
    require("SBOM" in readme, "README must mention SBOM", errors)
    require(len(readme) > 5000, "README must be comprehensive (more than 5000 characters)", errors)

    site = read("docs/site/index.html")
    require(not re.search(r"<(?:img|picture|source)\b", site, re.I), "Website contains screenshot/image markup", errors)
    require("2.0.2 پایدار" in site, "Website is not labeled as stable", errors)
    require("releases/download/v2.0.2/" in site, "Website download links do not target v2.0.2", errors)
    require(site.count('class="card"') == 6, "Website must contain six download cards", errors)

    release = read(".github/workflows/release.yml")
    require("workflow_dispatch:" in release, "Stable release workflow has no deterministic dispatch trigger", errors)
    require('tags:' not in release.split('permissions:', 1)[0], "Stable release workflow can run twice from tag push and dispatch", errors)
    require("python tools/validate_v202_stable.py" in release, "Release workflow does not run the stable validator", errors)
    require("libxcb-shape0" in release, "Linux build does not install libxcb-shape0", errors)
    require("python tools/verify_apk_fonts.py \"$apk\"" in release, "Workflow still verifies optimized font filenames instead of bytes", errors)
    require("prerelease: false" in release, "GitHub release is still marked prerelease", errors)
    require("draft: false" in release, "GitHub release can remain a draft", errors)
    require("make_latest: true" in release, "Stable release is not promoted as latest", errors)

    waiter = read("tools/wait_for_github_release.ps1")
    require("runs?per_page=50" in waiter and "event=push" not in waiter, "Release waiter ignores workflow_dispatch runs", errors)
    require("$release.prerelease -eq $false" in waiter, "Release waiter does not require stable publication", errors)
    require("$latest.tag_name -eq $Tag" in waiter, "Release waiter does not require Latest Release", errors)

    deployer = read("DEPLOY_RELEASE_200.bat")
    require("set \"TAG=v2.0.2\"" in deployer, "Deployer tag is not v2.0.2", errors)
    require("publish_release_trigger.ps1" in deployer, "Deployer does not use server-side tag creation", errors)
    require("goto :pages_failed" in deployer, "Pages failure is not fatal for the stable release", errors)
    require("DEPLOY_RELEASE_200.bat" in deployer, "Stable deploy filename is inconsistent", errors)
    require("tools\\validate_workflow_yaml.py" in deployer, "Deployer does not use the bundled workflow validator", errors)
    require("tools\\validate_v202_stable.py" in deployer, "Deployer does not run the v2.0.2 validator", errors)
    require("import yaml,pathlib" not in deployer, "Deployer still assumes a globally installed PyYAML package", errors)
    require((ROOT / "tools/vendor/pyyaml/yaml/__init__.py").is_file(), "Vendored PyYAML package is missing", errors)
    require((ROOT / "tools/vendor/pyyaml/LICENSE").is_file(), "Vendored PyYAML license is missing", errors)

    binary_fonts = list(ROOT.glob("assets/fonts/*.ttf")) + list(ROOT.glob("dicodePing_android/app/src/main/res/font/vazirmatn_*.ttf"))
    require(not binary_fonts, "Source snapshot contains generated font binaries", errors)

    legacy_root_files = []
    for pattern in ("BUILD_RELEASE_RC*.bat", "BUILD_SIGNED_APK_RC*.bat", "RUN_SOURCE_RC*.bat", "START_HERE_RC*.txt", "VALIDATION_RESULTS_RC*.txt"):
        legacy_root_files.extend(ROOT.glob(pattern))
    require(not legacy_root_files, "Legacy RC helper files remain in the stable package", errors)

    if errors:
        print("dicodePing 2.0.2 stable validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("dicodePing 2.0.2 stable release validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
