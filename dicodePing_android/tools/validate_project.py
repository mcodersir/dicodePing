from __future__ import annotations

from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

xml_files = [ROOT / "app/src/main/AndroidManifest.xml", *sorted((ROOT / "app/src/main/res").rglob("*.xml"))]
for path in xml_files:
    try:
        ET.parse(path)
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: {exc}")

base = {
    node.attrib["name"]
    for node in ET.parse(ROOT / "app/src/main/res/values/strings.xml").getroot()
    if node.tag == "string"
}
fa = {
    node.attrib["name"]
    for node in ET.parse(ROOT / "app/src/main/res/values-fa/strings.xml").getroot()
    if node.tag == "string"
}
if base != fa:
    errors.append(f"String resource mismatch: base-only={sorted(base-fa)}, fa-only={sorted(fa-base)}")

# Literal ASCII percent signs in non-format resources must opt out of Java Formatter parsing.
# Android Lint otherwise treats text such as "30% sample" as an invalid format string.
base_strings_root = ET.parse(ROOT / "app/src/main/res/values/strings.xml").getroot()
for node in base_strings_root:
    if node.tag != "string":
        continue
    value = "".join(node.itertext())
    if "%" not in value:
        continue
    valid_format = re.compile(
        r"%(?:%|n|(?:\d+\$)?(?:[-#+0,(<]*\d*(?:\.\d+)?[bBhHsScC]"
        r"|[-#+ 0,(<]*\d*(?:\.\d+)?[doxXeEfgGaA]|[tT][a-zA-Z]))"
    )
    remaining = valid_format.sub("", value)
    if "%" in remaining and node.attrib.get("formatted", "true").lower() != "false":
        errors.append(
            f"String resource {node.attrib.get('name')} contains a literal % and must declare formatted=\"false\""
        )

# Catch missing string resources before AAPT2 reaches processDebugResources.
resource_refs: set[str] = set()
for path in (ROOT / "app/src/main/res").rglob("*.xml"):
    resource_refs.update(re.findall(r"@string/([A-Za-z0-9_]+)", path.read_text(encoding="utf-8")))
missing_resource_refs = sorted(resource_refs - base)
if missing_resource_refs:
    errors.append(f"Missing @string resources: {missing_resource_refs}")

code_refs: set[str] = set()
for path in (ROOT / "app/src").rglob("*.kt"):
    source = path.read_text(encoding="utf-8")
    source = source.replace("android.R.string.", "android_R_string_")
    code_refs.update(re.findall(r"(?<!android\.)R\.string\.([A-Za-z0-9_]+)", source))
missing_code_refs = sorted(code_refs - base)
if missing_code_refs:
    errors.append(f"Missing R.string resources: {missing_code_refs}")

build_file = (ROOT / "app/build.gradle.kts").read_text(encoding="utf-8")
if 'versionName = "2.0.0-rc.1"' not in build_file:
    errors.append("versionName must be 2.0.0-rc.1 for this release")
if 'buildConfigField("String", "RELEASE_VERSION", "\\"2.0.0-rc.1\\"")' not in build_file:
    errors.append("RELEASE_VERSION must be 2.0.0-rc.1 for this release")

if "compileSdk = 36" not in build_file or "targetSdk = 36" not in build_file:
    errors.append("Android 2.0 RC1 must compile and target API 36")
root_build = (ROOT / "build.gradle.kts").read_text(encoding="utf-8")
wrapper = (ROOT / "gradle/wrapper/gradle-wrapper.properties").read_text(encoding="utf-8")
if "com.android.tools.build:gradle:8.10.1" not in root_build:
    errors.append("AGP 8.10.1 is required for supported API 36 builds")
if "gradle-8.11.1-bin.zip" not in wrapper:
    errors.append("Gradle 8.11.1 is required by AGP 8.10.x")
if not re.search(r"^\s*versionCode\s*=\s*55\s*$", build_file, re.MULTILINE):
    errors.append("Android 2.0 RC1 versionCode must be 55")
if 'setOf("arm64-v8a", "x86_64")' not in build_file:
    errors.append("Android public packages must be limited to 64-bit ABIs")
if "jniLibs.useLegacyPackaging = true" not in build_file:
    errors.append("Bundled executable helpers must be extracted into nativeLibraryDir")
if '"**/libaether.so", "**/libusque.so"' not in build_file:
    errors.append("Bundled Aether/Usque helpers must be preserved as APK native executables")

if 'implementation("ir.dicode.local:libv2ray:$coreVersion@aar")' not in build_file:
    errors.append("Android core must be resolved through the local Maven repository")
if '0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352' not in build_file:
    errors.append("Android core SHA-256 must be pinned in the Gradle preBuild check")
if 'implementation(files(' in build_file:
    errors.append("Direct local AAR file dependencies are forbidden because AGP may report a null extracted folder")

main_controller = (ROOT / "app/src/main/java/ir/dicode/ping/vpn/AndroidTetheringController.kt")
standard_controller = (ROOT / "app/src/standard/java/ir/dicode/ping/vpn/AndroidTetheringController.kt")
rooted_controller = (ROOT / "app/src/rooted/java/ir/dicode/ping/vpn/AndroidTetheringController.kt")
if main_controller.exists():
    errors.append(
        "AndroidTetheringController must exist only in the standard/rooted flavor source sets; "
        "the main source-set copy causes a Kotlin redeclaration"
    )
if not standard_controller.is_file() or not rooted_controller.is_file():
    errors.append("Android tethering controller flavors are incomplete")
else:
    standard_source = standard_controller.read_text(encoding="utf-8")
    rooted_source = rooted_controller.read_text(encoding="utf-8")
    if "ProcessBuilder" in standard_source or "iptables" in standard_source or '"su"' in standard_source:
        errors.append("Standard Android release must not contain root shell or iptables code")
    if "ProcessBuilder" not in rooted_source:
        errors.append("Rooted flavor lost its explicitly isolated advanced implementation")
if 'create("standard")' not in build_file or 'ENABLE_ROOT_TETHERING", "false"' not in build_file:
    errors.append("Standard Android distribution flavor is missing")
if 'android:allowBackup="false"' not in (ROOT / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8"):
    errors.append("Android backup must remain disabled for VPN configuration data")

crawler_source = (ROOT / "app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt").read_text(encoding="utf-8")
scanner_coordinator = (ROOT / "app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt").read_text(encoding="utf-8")
xray_builder = (ROOT / "app/src/main/java/ir/dicode/ping/xray/XrayConfigBuilder.kt").read_text(encoding="utf-8")
if 'fetchUrl("https://t.me/s/$channel")' not in crawler_source or "telegram.me" in crawler_source:
    errors.append("Android scanner must use only the canonical t.me preview endpoint")
if "Proxy.Type.SOCKS" not in crawler_source or ".proxy(scannerProxy)" not in crawler_source:
    errors.append("Android Telegram crawler must route through the embedded Xray SOCKS inbound")
if "requireNotNull(preflight)" in crawler_source or "channels.take(4)" in crawler_source:
    errors.append("Android crawler must not abort the full scan because the first channels fail")
if 'const val SCANNER_SOCKS_PORT = 18089' not in xray_builder:
    errors.append("Xray scanner SOCKS port is missing")
if '.put("tag", "scanner-socks")' not in xray_builder or '.put("protocol", "socks")' not in xray_builder:
    errors.append("Xray scanner SOCKS inbound is missing")
if "proxy-side DNS" not in scanner_coordinator:
    errors.append("Scanner route diagnostics must report proxy-side DNS")

visible_code = "\n".join(
    (ROOT / rel).read_text(encoding="utf-8")
    for rel in (
        "app/src/main/java/ir/dicode/ping/ui/HomeFragment.kt",
        "app/src/main/java/ir/dicode/ping/ui/ServerAdapter.kt",
        "app/src/main/java/ir/dicode/ping/MainActivity.kt",
    )
)
for leaked in ("server.protocol", "${it.protocol}", "${server.protocol}"):
    if leaked in visible_code:
        errors.append(f"Protocol details are exposed by UI code: {leaked}")

for required in (
    "build_apk.bat",
    "build_apk.sh",
    "INSTALL_ANDROID_CORE.txt",
    "local-maven/ir/dicode/local/libv2ray/26.7.11/libv2ray-26.7.11.pom",
    "app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt",
):
    if not (ROOT / required).exists():
        errors.append(f"Missing required file: {required}")

if list(ROOT.rglob("*.ttf")) or list(ROOT.rglob("*.otf")):
    errors.append("Do not bundle font binaries; this project uses the Android downloadable font provider")


external_core_source = (ROOT / "app/src/main/java/ir/dicode/ping/core/AndroidExternalCoreProcess.kt").read_text(encoding="utf-8")
external_command_source = (ROOT / "app/src/main/java/ir/dicode/ping/core/ExternalCoreCommandBuilder.kt").read_text(encoding="utf-8")
vpn_service_source = (ROOT / "app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text(encoding="utf-8")
settings_source = (ROOT / "app/src/main/java/ir/dicode/ping/ui/SettingsFragment.kt").read_text(encoding="utf-8")
home_source = (ROOT / "app/src/main/java/ir/dicode/ping/ui/HomeFragment.kt").read_text(encoding="utf-8")
manifest_source = (ROOT / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
if 'android:extractNativeLibs="true"' not in manifest_source:
    errors.append("Bundled Aether/Usque executables must be extracted by PackageManager")
for token in ("--quick-reconnect", "--h2", "--fragment", "--always-reconnect", "--http2"):
    if token not in external_command_source:
        errors.append(f"External-core runtime lost required transport option: {token}")
if "startExternalCoreWithFallback" not in vpn_service_source or "EXTERNAL_VERIFY_TIMEOUT_MS" not in vpn_service_source:
    errors.append("External cores must use real-traffic verification with automatic fallback")
if "core_activation_guide_aether" not in settings_source or "openHomePage" not in settings_source:
    errors.append("Aether/WARP activation must guide the user to Home and the Connect button")
if "renderExternalCoreTarget" not in home_source:
    errors.append("Home must show the active external core instead of an unrelated Xray server")

if errors:
    print("Validation failed:")
    for item in errors:
        print(f"- {item}")
    sys.exit(1)

print(f"Validated {len(xml_files)} XML files")
print(f"Validated {len(base)} localized strings")
print("Version is 2.0.0-rc.1")
print("Project structure is ready for Android build")
