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

# Catch missing string resources before AAPT2 reaches processDebugResources.
resource_refs: set[str] = set()
for path in (ROOT / "app/src/main/res").rglob("*.xml"):
    resource_refs.update(re.findall(r"@string/([A-Za-z0-9_]+)", path.read_text(encoding="utf-8")))
missing_resource_refs = sorted(resource_refs - base)
if missing_resource_refs:
    errors.append(f"Missing @string resources: {missing_resource_refs}")

code_refs: set[str] = set()
for path in (ROOT / "app/src/main/java").rglob("*.kt"):
    source = path.read_text(encoding="utf-8")
    source = source.replace("android.R.string.", "android_R_string_")
    code_refs.update(re.findall(r"(?<!android\.)R\.string\.([A-Za-z0-9_]+)", source))
missing_code_refs = sorted(code_refs - base)
if missing_code_refs:
    errors.append(f"Missing R.string resources: {missing_code_refs}")

build_file = (ROOT / "app/build.gradle.kts").read_text(encoding="utf-8")
if 'versionName = "0.1.2"' not in build_file:
    errors.append("versionName must be 0.1.2 for this release")

if 'implementation("ir.dicode.local:libv2ray:$coreVersion@aar")' not in build_file:
    errors.append("Android core must be resolved through the local Maven repository")
if '367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e' not in build_file:
    errors.append("Android core SHA-256 must be pinned in the Gradle preBuild check")
if 'implementation(files(' in build_file:
    errors.append("Direct local AAR file dependencies are forbidden because AGP may report a null extracted folder")

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
    "local-maven/ir/dicode/local/libv2ray/26.6.2/libv2ray-26.6.2.pom",
    "app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt",
):
    if not (ROOT / required).exists():
        errors.append(f"Missing required file: {required}")

if list(ROOT.rglob("*.ttf")) or list(ROOT.rglob("*.otf")):
    errors.append("Do not bundle font binaries; this project uses the Android downloadable font provider")

if errors:
    print("Validation failed:")
    for item in errors:
        print(f"- {item}")
    sys.exit(1)

print(f"Validated {len(xml_files)} XML files")
print(f"Validated {len(base)} localized strings")
print("Version is 0.1.2")
print("Project structure is ready for Android build")
