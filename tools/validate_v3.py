from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def require(path: str, *markers: str) -> str:
    target = ROOT / path
    if not target.is_file():
        errors.append(f"Missing required file: {path}")
        return ""
    text = target.read_text(encoding="utf-8", errors="replace")
    for marker in markers:
        if marker not in text:
            errors.append(f"{path}: missing marker {marker!r}")
    return text


require(
    "dicodeping/constants.py",
    'VERSION = "3.0.0"',
    'RELEASE_VERSION = "3.0.0-pre.4"',
    'DEFAULT_SUBSCRIPTION_URL = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt"',
    'base / APP_NAME / "v3"',
)
require("app.py", "CoreHostClient", "AppService", "MainWindow")
require("dicodeping/__init__.py", '__version__ = "3.0.0-pre.4"')
require("tools/windows_version_info.txt", "3.0.0.0", "3.0.0-pre.4")
require("dicodeping/subscription.py", "DEFAULT_SUBSCRIPTION_MIRRORS", "fetch_subscription")
require("dicodeping/service.py", "runtime.sync_source", "runtime.latency", 'row.source_id.startswith("scanner-")')
require("dicodeping/scanner.py", "service.runtime.probe_payload", "crawl_telegram_channels", "service.runtime.sync_source")
require(
    "dicodeping/ui.py",
    "class OverviewPage",
    "class ProfilesPage",
    "class ScannerPage",
    "class RoutingPage",
    "class LogsPage",
    "class AboutPage",
    "Connection Center" if False else "مرکز اتصال",
    "dns_strategy",
    "dns_preference",
    "core_preference",
)
require("dicodeping/client/host.py", '"probe_payload"', '"dicodePing.CoreHost')

require(
    "corehost/dicodePing.CoreHost.csproj",
    "third_party\\network-engine\\runtime\\ServiceLib\\ServiceLib.csproj",
    "dicodePing.CoreHost",
)
require(
    "corehost/Program.cs",
    "ConfigHandler.AddBatchServers",
    "CoreConfigContextBuilder.BuildAll",
    "CoreManager.Instance.LoadCore",
    "SysProxyHandler.UpdateSysProxy",
    "SpeedtestService",
    "DomainStrategy4Singbox",
    '"core_preference"',
    '"probe_payload"',
)

workflow = require(
    ".github/workflows/release-v3.yml",
    '"v3.*-pre.*"',
    "windows-2025",
    "ubuntu-24.04",
    "macos-15-intel",
    "macos-15",
    "build_apk.sh",
    "--prerelease",
    "GH_TOKEN: ${{ github.token }}",
    "tests/test_release.py",
)
for marker in (
    "dicodePing-v3.0.0-pre.4-windows-x64.exe",
    "dicodePing-v3.0.0-pre.4-linux-x86_64.tar.gz",
    "dicodePing-v3.0.0-pre.4-macos-arm64.dmg",
    "dicodePing-v3.0.0-pre.4-macos-x86_64.dmg",
    "dicodePing-v3.0.0-pre.4-android.apk",
):
    if marker not in workflow:
        errors.append(f"Release workflow missing artifact: {marker}")

bat = require(
    "RELEASE_V3_PRERELEASE.bat",
    "mcodersir/dicodePing",
    "git clone",
    "git push origin",
    "git tag -a",
)
if "GH_TOKEN is not set" in bat or "if not defined GH_TOKEN" in bat:
    errors.append("Release BAT must not require a local GH_TOKEN")
if "robocopy" in bat.lower():
    errors.append("Release BAT must use the manifest-verified Python sync instead of robocopy")
if "sync_release_tree.py" not in bat:
    errors.append("Release BAT must use tools/sync_release_tree.py")
if "gh auth setup-git" in bat:
    errors.append("Release BAT must use existing Git authentication instead of rewriting it through gh")
for secret_literal in ("ghp_", "github_pat_", "gho_", "ghs_"):
    if secret_literal in bat:
        errors.append(f"Release BAT contains a token-like literal: {secret_literal}")

require(
    "dicodePing_android/app/build.gradle.kts",
    'versionCode = 73',
    'versionName = "3.0.0-pre.4"',
    'setOf("arm64-v8a", "armeabi-v7a", "x86_64")',
)
require("dicodePing_android/app/src/main/java/ir/dicode/ping/data/SettingsStore.kt", 'getSharedPreferences("dicodeping_v3"')
require(
    "dicodePing_android/app/src/main/java/ir/dicode/ping/net/ConfigParser.kt",
    "hysteria2|hy2",
    "parseHysteria2(raw)",
    '.put("protocol", "hysteria")',
    '.put("network", "hysteria")',
    '.put("hysteriaSettings", hysteriaSettings)',
    '.put("finalmask", finalMask)',
)
require("THIRD_PARTY_NOTICES.md", "2dust/v2rayN ServiceLib", "XTLS/Xray-core", "SagerNet/sing-box")
require("LICENSE", "GNU GENERAL PUBLIC LICENSE", "Version 3")
require("licenses/PRODUCT_MIT_NOTICE.txt", "MIT License")
require("third_party/network-engine/LICENSE", "GNU GENERAL PUBLIC LICENSE")
require("third_party/network-engine/runtime/ServiceLib/ServiceLib.csproj", "<OutputType>Library</OutputType>")
require("tools/prepare_engine.py", 'XRAY_VERSION = "26.7.11"', 'SING_BOX_VERSION = "1.13.12"', "dotnet", "publish", "dicodePing.CoreHost.csproj")
require("runtime_assets/RUNTIME_ASSETS.lock.json", '"release": "3.0.0-pre.4"', '"Xray-windows-64.zip"', '"runtime_version": "26.7.11"')
require("tools/fetch_runtime_assets.py", "XRAY_ASSETS", "ANDROID_AAR_SHA256", "--verify-only")
require("PREPARE_V3_RUNTIME.bat", "--verify-only", "No network access was used")
require("REPAIR_V3_RUNTIME.bat", "fetch_runtime_assets.py")
require("MAKE_COMPLETE_V3_ZIP.bat", "package_complete_v3.py")
require("tools/package_complete_v3.py", "verify_runtime_bundle", "complete.zip")
require("tools/sync_release_tree.py", "SOURCE_MANIFEST.sha256", "Preserved .git", "source checksum mismatch")

# Version 3 ships one release document and one release workflow.
release_docs = sorted(p.name for p in (ROOT / "docs" / "releases").glob("*.md"))
if release_docs != ["v3.0.0-pre.4.md"]:
    errors.append(f"Unexpected release docs: {release_docs}")

release_workflows = [p.name for p in (ROOT / ".github/workflows").glob("*release*.yml")]
if release_workflows != ["release-v3.yml"]:
    errors.append(f"Competing release workflows remain: {release_workflows}")

if errors:
    print("dicodePing 3.0.0-pre.4 validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)
print("dicodePing 3.0.0-pre.4 source validation passed")
