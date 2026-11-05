#!/usr/bin/env python3
"""Check upgrade identity, signing certificate and native Xray/Fox packaging."""
import os, pathlib, re, subprocess, zipfile, json, hashlib
from verify_elf_alignment import verify_elf
root = pathlib.Path("dist-android")
tools = pathlib.Path(os.environ["ANDROID_HOME"]) / "build-tools" / "37.0.0"
expected_cert = "0a483317ee0bd0e2aea48d2be72c30f206d3cceb3f178ea18ca22a17d6cdfcc0"
abis = {"universal": 0, "arm64-v8a": 1, "armeabi-v7a": 2, "x86_64": 3, "x86": 4}
for edition in ['', 'TV-']:
 for abi, suffix in abis.items():
    apk = root / f"DicodePing-{edition}4.9.94-{abi}.apk"
    signer = subprocess.run([str(tools / "apksigner"), "verify", "--print-certs", str(apk)], check=True, capture_output=True, text=True).stdout
    certs = re.findall(r"certificate SHA-256 digest: ([0-9a-fA-F]+)", signer)
    assert certs and all(c.lower() == expected_cert for c in certs), "APK signing identity changed"
    manifest = subprocess.run([str(tools / "aapt2"), "dump", "badging", str(apk)], check=True, capture_output=True, text=True).stdout
    package = "ir.dicode.ping.tv" if edition else "ir.dicode.ping.fdroid"
    assert f"name='{package}'" in manifest, "Android application ID changed"
    code = "4409940" if edition else "45994000"
    assert "versionName='4.9.94'" in manifest and f"versionCode='{code}'" in manifest, "APK version mismatch"
    assert "targetSdkVersion:'36'" in manifest, "APK targets a preview SDK"
    subprocess.run([str(tools / "zipalign"), "-c", "-P", "16", "-v", "4", str(apk)], check=True, stdout=subprocess.DEVNULL)
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            parts = name.split('/')
            if len(parts) == 3 and parts[0] == 'lib' and name.endswith('.so'):
                verify_elf(archive.read(name), parts[1], name)
        for item in json.loads(pathlib.Path("scripts/runtime-pins-4.9.94.json").read_text())["android_geodata"]:
            content = archive.read("assets/" + item["name"])
            assert hashlib.sha256(content).hexdigest() == item["sha256"], "Missing or altered Android Geo asset: " + item["name"]
        for notice in ["NOTICE.txt", "LICENSE-GPL-3.0.txt", "LICENSE-CC-BY-SA-4.0.txt"]:
            assert "assets/routing-data/" + notice in archive.namelist(), "Routing data attribution is missing"
        packaged = [a for a in abis if a != "universal"] if abi == "universal" else [abi]
        for architecture in packaged:
            storage = archive.read(f"lib/{architecture}/libmmkv.so")
            assert storage[:4] == b"\x7fELF" and storage[4] == (2 if architecture in ("arm64-v8a", "x86_64") else 1), "Storage native library missing or architecture mismatch"
            assert f"lib/{architecture}/libsingbox.so" in archive.namelist(), "Standalone sing-box is missing"
            fox = archive.read(f"lib/{architecture}/libdicodefox.so")
            assert fox[:4] == b"\x7fELF" and fox[4] == (2 if architecture in ("arm64-v8a", "x86_64") else 1), "Fox helper architecture mismatch"
        assert "assets/singbox/LICENSE.txt" in archive.namelist(), "Standalone sing-box license is missing"
        for notice in ["LICENSE-FoxyVPN.txt", "LICENSE-sing-box.txt", "LICENSE-Go.txt", "LICENSE-DicodePing.txt", "THIRD_PARTY_NOTICES-Go.txt"]:
            assert "assets/fox/" + notice in archive.namelist(), "Fox license is missing: " + notice
    print("Verified signed upgrade and native core:", apk.name)
