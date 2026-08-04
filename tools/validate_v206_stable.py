from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLE_TEST_URL = "http://captive.apple.com/hotspot-detect.html"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    constants = read("dicodeping/constants.py")
    package = read("dicodeping/__init__.py")
    gradle = read("dicodePing_android/app/build.gradle.kts")
    workflow = read(".github/workflows/release.yml")
    net = read("dicodeping/net.py")
    xray = read("dicodeping/xray.py")
    shared_quality = read("shared/connection_quality.py")
    crawler = read("dicodeping/crawler.py")
    runtime = read("dicodeping/rc7_runtime.py")
    ci_workflow = read(".github/workflows/ci.yml")
    codeql_workflow = read(".github/workflows/codeql.yml")
    android_build = read("dicodePing_android/build_apk.sh")
    android_repo = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    core_bridge = read("dicodePing_android/app/src/main/java/ir/dicode/ping/xray/CoreBridge.kt")
    vpn_service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    network_security = read("dicodePing_android/app/src/main/res/xml/network_security_config.xml")

    require(re.search(r'(?m)^VERSION = "2\.0\.6"$', constants) is not None,
            "VERSION must be 2.0.6", errors)
    require(re.search(r'(?m)^RELEASE_VERSION = "2\.0\.6"$', constants) is not None,
            "RELEASE_VERSION must be 2.0.6", errors)
    require('__version__ = "2.0.6"' in package,
            "Python package version must be 2.0.6", errors)
    require('versionCode = 62' in gradle, "Android versionCode must be 62", errors)
    require('versionName = "2.0.6"' in gradle,
            "Android versionName must be 2.0.6", errors)
    require('buildConfigField("String", "RELEASE_VERSION", "\\"2.0.6\\"")' in gradle,
            "Android RELEASE_VERSION is inconsistent", errors)

    for builder in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = read(builder)
        require('APP_VERSION = "2.0.6"' in body,
                f"{builder} has the wrong APP_VERSION", errors)
        require('"--collect-data"' in body and '"certifi"' in body,
                f"{builder} does not package certifi", errors)
        require('app_v200.py' in body, f"{builder} does not package app_v200.py", errors)

    requirements = read("requirements.txt")
    require(re.search(r'(?m)^certifi==\d{4}\.\d+\.\d+$', requirements) is not None,
            "Runtime certifi dependency is not pinned", errors)
    require("ssl.create_default_context" in net and "certifi.where()" in net,
            "Portable verified TLS context is missing", errors)
    tls12_marker = "minimum_version = ssl.TLSVersion.TLSv1_2"
    tls_paths = {
        "dicodeping/net.py": net,
        "dicodeping/xray.py": xray,
        "shared/connection_quality.py": shared_quality,
        "dicodeping/crawler.py": crawler,
    }
    for relative, body in tls_paths.items():
        require(
            "ssl.CERT_NONE" not in body and "check_hostname = False" not in body,
            f"TLS verification was weakened in {relative}",
            errors,
        )
        require(
            tls12_marker in body,
            f"{relative} does not require TLS 1.2 or newer",
            errors,
        )
    require("create_tls_context()" in xray,
            "Desktop SOCKS HTTPS probes do not use the verified CA context", errors)

    require(APPLE_TEST_URL in constants, "Apple connectivity URL is not the primary desktop health URL", errors)
    require(APPLE_TEST_URL in xray, "Apple connectivity URL is not used by desktop Xray/TUN tests", errors)
    require(APPLE_TEST_URL in core_bridge, "Apple connectivity URL is not used by Android core tests", errors)

    require("def _enrich_records_parallel" in runtime,
            "Desktop ping/geo parallel pipeline is missing", errors)
    runtime_prefix = runtime.split("def _install_ui_patch", 1)[0]
    require("from PySide6" not in runtime_prefix and "import PySide6" not in runtime_prefix,
            "Connectivity runtime eagerly imports Qt/EGL on headless Linux", errors)
    require("libegl1" in ci_workflow and "libgl1" in ci_workflow,
            "CI does not install the minimal Qt Linux runtime", errors)
    require('gradleProperty("dicodePing.codeql")' in gradle and "return@doLast" in gradle,
            "CodeQL-only native-runtime verification gate is missing", errors)
    require("-PdicodePing.codeql=true assembleDebug" in codeql_workflow,
            "CodeQL does not opt into its compile-only native-runtime gate", errors)
    require("actions/setup-python@v6" in codeql_workflow and 'python-version: "3.12"' in codeql_workflow,
            "CodeQL does not provision the pinned Python used for Android resource preparation", errors)
    font_prepare_marker = "python tools/prepare_vazirmatn.py --android"
    gradle_build_marker = "-PdicodePing.codeql=true assembleDebug"
    require(font_prepare_marker in codeql_workflow,
            "CodeQL does not materialize the pinned bundled Vazirmatn resources", errors)
    if font_prepare_marker in codeql_workflow and gradle_build_marker in codeql_workflow:
        require(codeql_workflow.index(font_prepare_marker) < codeql_workflow.index(gradle_build_marker),
                "CodeQL prepares Android fonts after Gradle resource linking", errors)
    require("for font in regular medium bold; do" in codeql_workflow and
            'vazirmatn_${font}.ttf' in codeql_workflow and 'test -s "$file"' in codeql_workflow,
            "CodeQL does not verify all generated Android font resources", errors)
    require("dicodePing.codeql" not in workflow and "dicodePing.codeql" not in android_build,
            "A release/APK build incorrectly bypasses native-runtime verification", errors)
    require("python tools/prepare_bundled_cores.py" in android_build,
            "Android release build no longer prepares Aether and Usque", errors)
    require("ping_future = pool.submit(" in runtime and "geo_future = pool.submit(" in runtime and "_test_records, records" in runtime and "_apply_geo, service" in runtime,
            "Desktop ping and geo are not submitted concurrently", errors)
    require("except OSError:\n            return None, None" in runtime and runtime.index("return None, None") < runtime.index("probe_outbound_delay"),
            "Desktop dead-endpoint TCP prefilter is missing", errors)
    require("NORMAL_TCP_PROBE_CONCURRENCY = 20" in android_repo,
            "Android normal ping concurrency is not enabled", errors)
    require("fun locateAndPing" in android_repo and "parallelTcpProbe" in android_repo,
            "Android ping/geo parallel pipeline is incomplete", errors)
    require("addAllowedApplication(packageName)" not in vpn_service and ".filter { it.isNotBlank() && it != packageName }" in vpn_service,
            "Android still routes the core into its own VPN", errors)

    font_generator = read("tools/prepare_vazirmatn.py")
    require("xmlns:android" not in font_generator and "android:font=" not in font_generator,
            "Generated Vazirmatn XML reintroduces API-26-only android font attributes", errors)
    require("xmlns:app" in font_generator and "schemas.android.com/apk/res-auto" in font_generator,
            "Generated Vazirmatn XML does not use the AndroidX support namespace", errors)

    font_values = ROOT / "dicodePing_android/app/src/main/res/values/font_certs.xml"
    font_values_v26 = ROOT / "dicodePing_android/app/src/main/res/values-v26/font_certs.xml"
    require(not font_values.exists() and not font_values_v26.exists(),
            "Obsolete downloadable-font certificate resource remains", errors)
    prepare = read("tools/prepare_build_workspace.py")
    require("LEGACY_ANDROID_FONT_RESOURCES" in prepare and "fontProvider" in prepare,
            "Workspace cleanup does not remove stale downloadable-font resources", errors)

    require("workflow_dispatch:" in workflow, "Release workflow must be manually dispatchable", errors)
    require("python tools/validate_v206_stable.py" in workflow,
            "Release workflow does not run the stable v2.0.6 validator", errors)
    require("tag_name: v2.0.6" in workflow, "Release tag is wrong", errors)
    require("prerelease: false" in workflow and "draft: false" in workflow and "make_latest: true" in workflow,
            "Release must be a published stable Latest release", errors)
    require("2.0.6-rc.1" not in workflow and "validate_v206_prerelease" not in workflow,
            "Prerelease markers remain in the stable workflow", errors)
    macos = workflow.split("  macos:", 1)[1].split("  android:", 1)[0]
    require("DICODEPING_DISCOVERY_SMOKE=1" in macos and "--discovery-smoke" in macos,
            "Packaged macOS discovery/TLS smoke test is missing", errors)

    site = read("docs/site/index.html")
    require("dicodePing 2.0.6 پایدار" in site,
            "Download site is not labeled stable", errors)
    require("releases/download/v2.0.6/" in site,
            "Download site does not target v2.0.6", errors)
    require("2.0.6-rc.1" not in site and "پیش‌انتشار" not in site,
            "Prerelease labels remain on the stable site", errors)
    require((ROOT / "docs/releases/v2.0.6.md").is_file(),
            "Stable release notes are missing", errors)

    deployer_path = ROOT / "DEPLOY_RELEASE_206_STABLE.bat"
    if deployer_path.is_file():
        deployer = deployer_path.read_text(encoding="utf-8-sig")
        for marker in (
            'set "TAG=v2.0.6"',
            "tools\\validate_v206_stable.py",
            "PUBLISH_HELPER",
            "--verify-existing-only",
            "ANDROID_KEYSTORE_BASE64",
        ):
            require(marker in deployer, f"Deployer marker missing: {marker}", errors)
        publisher_path = ROOT / "release-tools/publish_verified_release.py"
        require(publisher_path.is_file(), "Verified GitHub publisher helper is missing", errors)
        if publisher_path.is_file():
            publisher = publisher_path.read_text(encoding="utf-8-sig")
            for marker in (
                "def merge_pr",
                "def dispatch_release",
                '"prerelease"',
                '"--log-failed"',
                "webbrowser.open",
                'REQUIRED_PR_WORKFLOWS = ("ci.yml", "codeql.yml")',
                "commits/{head_sha}/check-runs?filter=latest&per_page=100",
                "commits/{head_sha}/statuses?per_page=100",
                "Checks for exact PR head",
                "def ensure_advanced_codeql_setup",
                "code-scanning/default-setup",
                '"state=not-configured"',
                "no CodeQL check is skipped",
                "def failed_check_run_diagnostics",
                "check-runs/{check_id}/annotations?per_page=100",
                "format_check_run_diagnostics",
            ):
                require(marker in publisher, f"Publisher marker missing: {marker}", errors)
        require("--ensure-codeql-advanced" in deployer,
                "Deployer does not reconcile GitHub CodeQL default and advanced setup", errors)
        require('for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"' in deployer,
                "Deployer does not canonicalize SOURCE_DIR", errors)
        require('set "SOURCE_DIR=%~dp0"' not in deployer,
                "Deployer still uses a trailing-backslash SOURCE_DIR", errors)
        require('release-tools\\stage_snapshot.py' in deployer and
                'RELEASE_SOURCE_MANIFEST.sha256' in deployer,
                "Deployer does not use exact checksum-manifest staging", errors)
        require('git rm -r -f --ignore-unmatch .' not in deployer,
                "Deployer still recreates the whole tree and loses Git file modes", errors)
        stage_snapshot = read("release-tools/stage_snapshot.py")
        require("def prune_destination" in stage_snapshot and
                "retains their index modes" in stage_snapshot,
                "Manifest staging does not preserve base-branch Git modes", errors)
        require('robocopy "%SOURCE_DIR%" "%STAGE_DIR%"' not in deployer,
                "Deployer still copies unlisted files from dirty extracted folders", errors)
        require("ghp_" not in deployer and "GITHUB_TOKEN=" not in deployer,
                "Deployer must not embed a GitHub token", errors)

    if errors:
        print("dicodePing v2.0.6 stable validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("dicodePing v2.0.6 stable validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
