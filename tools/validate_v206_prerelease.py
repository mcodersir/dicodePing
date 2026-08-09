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
    package = read("dicodeping/__init__.py")
    gradle = read("dicodePing_android/app/build.gradle.kts")
    workflow = read(".github/workflows/release.yml")
    net = read("dicodeping/net.py")
    runtime = read("dicodeping/rc7_runtime.py")
    android_repo = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    vpn_service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")

    require(re.search(r'(?m)^VERSION = "2\.0\.6"$', constants) is not None,
            "VERSION must be 2.0.6", errors)
    require(re.search(r'(?m)^RELEASE_VERSION = "2\.0\.6-rc\.1"$', constants) is not None,
            "RELEASE_VERSION must be 2.0.6-rc.1", errors)
    require('__version__ = "2.0.6rc1"' in package,
            "Python package version must be 2.0.6rc1", errors)
    require('versionCode = 62' in gradle, "Android versionCode must be 62", errors)
    require('versionName = "2.0.6-rc.1"' in gradle,
            "Android versionName must be 2.0.6-rc.1", errors)
    require('buildConfigField("String", "RELEASE_VERSION", "\\"2.0.6-rc.1\\"")' in gradle,
            "Android RELEASE_VERSION is inconsistent", errors)

    for builder in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = read(builder)
        require('APP_VERSION = "2.0.6-rc.1"' in body,
                f"{builder} has the wrong APP_VERSION", errors)
        require('"--collect-data"' in body and '"certifi"' in body,
                f"{builder} does not package certifi", errors)
        require('app_v200.py' in body, f"{builder} does not package app_v200.py", errors)

    requirements = read("requirements.txt")
    require(re.search(r'(?m)^certifi==\d{4}\.\d+\.\d+$', requirements) is not None,
            "Runtime certifi dependency is not pinned", errors)
    require("ssl.create_default_context" in net and "certifi.where()" in net,
            "Portable verified TLS context is missing", errors)
    require("ssl.CERT_NONE" not in net and "check_hostname = False" not in net,
            "TLS verification was weakened", errors)

    require("def _enrich_records_parallel" in runtime,
            "Desktop ping/geo parallel pipeline is missing", errors)
    require("ping_future = pool.submit(" in runtime and "geo_future = pool.submit(" in runtime and "_test_records, records" in runtime and "_apply_geo, service" in runtime,
            "Desktop ping and geo are not submitted concurrently", errors)
    require("except OSError:\n            return None, None" in runtime and runtime.index("return None, None") < runtime.index("probe_outbound_delay"),
            "Desktop dead-endpoint TCP prefilter is missing", errors)
    require("NORMAL_TCP_PROBE_CONCURRENCY = 20" in android_repo,
            "Android normal ping concurrency is not enabled", errors)
    require("fun locateAndPing" in android_repo and "parallelTcpProbe" in android_repo,
            "Android ping/geo parallel pipeline is incomplete", errors)
    require("addAllowedApplication(packageName)" not in vpn_service and ".filter { it.isNotBlank() && it != packageName }" in vpn_service,
            "Android still routes the Xray process into its own VPN", errors)

    require("workflow_dispatch:" in workflow, "Release workflow must be manually dispatchable", errors)
    require("python tools/validate_v206_prerelease.py" in workflow,
            "Release workflow does not run the v2.0.6 validator", errors)
    require("tag_name: v2.0.6-rc.1" in workflow, "Release tag is wrong", errors)
    require("prerelease: true" in workflow and "make_latest: false" in workflow,
            "Release must be prerelease and must not replace Latest", errors)
    macos = workflow.split("  macos:", 1)[1].split("  android:", 1)[0]
    require("DICODEPING_DISCOVERY_SMOKE=1" in macos and "--discovery-smoke" in macos,
            "Packaged macOS discovery/TLS smoke test is missing", errors)

    site = read("docs/site/index.html")
    require("2.0.6-rc.1 پیش‌انتشار" in site,
            "Download site is not labeled as prerelease", errors)
    require("releases/download/v2.0.6-rc.1/" in site,
            "Download site does not target v2.0.6-rc.1", errors)
    require((ROOT / "docs/releases/v2.0.6-rc.1.md").is_file(),
            "Release notes are missing", errors)

    deployer = read("DEPLOY_RELEASE_206_PRERELEASE.bat")
    for marker in (
        'set "TAG=v2.0.6-rc.1"',
        "tools\\validate_v206_prerelease.py",
        "gh pr merge",
        "gh workflow run",
        "isPrerelease",
    ):
        require(marker in deployer, f"Deployer marker missing: {marker}", errors)
    require('for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"' in deployer,
            "Deployer does not canonicalize SOURCE_DIR without a trailing backslash", errors)
    require('set "SOURCE_DIR=%~dp0"' not in deployer,
            "Deployer still uses the robocopy-breaking trailing-backslash source path", errors)
    require('robocopy "%SOURCE_DIR%" "%STAGE_DIR%"' in deployer and
            'set "ROBOCOPY_CODE=!ERRORLEVEL!"' in deployer,
            "Deployer robocopy invocation is not quote-safe", errors)
    require("ghp_" not in deployer and "GITHUB_TOKEN=" not in deployer,
            "Deployer must not embed a GitHub token", errors)

    if errors:
        print("dicodePing v2.0.6-rc.1 validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("dicodePing v2.0.6-rc.1 prerelease validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
