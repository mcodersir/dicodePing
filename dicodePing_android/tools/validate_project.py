from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

for path in [ROOT / "app/src/main/AndroidManifest.xml", *sorted((ROOT / "app/src/main/res").rglob("*.xml"))]:
    try:
        ET.parse(path)
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: {exc}")

build = (ROOT / "app/build.gradle.kts").read_text(encoding="utf-8")
for marker in (
    'versionCode = 71',
    'versionName = "3.0.0-pre.2"',
    'buildConfigField("String", "RELEASE_VERSION", "\\"3.0.0-pre.2\\"")',
    'setOf("arm64-v8a", "armeabi-v7a", "x86_64")',
    'implementation("ir.dicode.local:libv2ray:$coreVersion@aar")',
    'coreSha256 = "0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"',
):
    if marker not in build:
        errors.append(f"Missing Android V3 build marker: {marker}")

source_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "app/src").rglob("*.kt"))

vpn = (ROOT / "app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text(encoding="utf-8")
for marker in ("CoreBridge(applicationContext)", "XrayConfigBuilder.build(", "core!!.start(runtimeConfig, tun!!.fd)", "verifyProxyConnection()"):
    if marker not in vpn:
        errors.append(f"Android runtime integration missing: {marker}")

parser = (ROOT / "app/src/main/java/ir/dicode/ping/net/ConfigParser.kt").read_text(encoding="utf-8")
for marker in (
    "hysteria2|hy2",
    "parseHysteria2(raw)",
    '.put("protocol", "hysteria")',
    '.put("network", "hysteria")',
    '.put("hysteriaSettings", hysteriaSettings)',
    '.put("finalmask", finalMask)',
    '"salamander"',
):
    if marker not in parser:
        errors.append(f"Android Hysteria2 support missing: {marker}")

crawler = (ROOT / "app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt").read_text(encoding="utf-8")
if "hysteria2|hy2" not in crawler:
    errors.append("Android scanner must preserve Hysteria2 configs")
repository = (ROOT / "app/src/main/java/ir/dicode/ping/data/AppRepository.kt").read_text(encoding="utf-8")
if 'setOf("kcp", "quic", "hysteria", "hysteria2", "wireguard")' not in repository:
    errors.append("Android Hysteria2 must bypass the TCP-only scanner precheck")

settings = (ROOT / "app/src/main/java/ir/dicode/ping/data/SettingsStore.kt").read_text(encoding="utf-8")
if ("active" + "Core") in settings or "active_core" in settings:
    errors.append("Android must not retain a runtime-selector setting")

base = ET.parse(ROOT / "app/src/main/res/values/strings.xml").getroot()
fa = ET.parse(ROOT / "app/src/main/res/values-fa/strings.xml").getroot()
base_names = {n.attrib["name"] for n in base if n.tag == "string" and n.attrib.get("translatable", "true") != "false"}
fa_names = {n.attrib["name"] for n in fa if n.tag == "string"}
if base_names != fa_names:
    errors.append(f"String resource mismatch: base-only={sorted(base_names-fa_names)[:10]}, fa-only={sorted(fa_names-base_names)[:10]}")

if errors:
    print("Android V3 validation failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)
print("Android V3 project validation passed")
