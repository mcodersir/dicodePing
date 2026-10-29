#!/usr/bin/env python3
"""Check upgrade identity, signing certificate and native Xray/Fox packaging."""
import os, pathlib, re, subprocess, zipfile, json, hashlib
from verify_elf_alignment import verify_elf
root = pathlib.Path("dist-android")
tools = pathlib.Path(os.environ["ANDROID_HOME"]) / "build-tools" / "37.0.0"
expected_cert = "0a483317ee0bd0e2aea48d2be72c30f206d3cceb3f178ea18ca22a17d6cdfcc0"
abis = {"universal": 0, "arm64-v8a": 1, "armeabi-v7a": 2, "x86_64": 3, "x86": 4}
for abi, suffix in abis.items():
    apk = root / f"DicodePing-4.9.91-{abi}.apk"
    signer = subprocess.run([str(tools / "apksigner"), "verify", "--print-certs", str(apk)], check=True, capture_output=True, text=True).stdout
    certs = re.findall(r"certificate SHA-256 digest: ([0-9a-fA-F]+)", signer)
    assert certs and all(c.lower() == expected_cert for c in certs), "APK signing identity changed"
    manifest = subprocess.run([str(tools / "aapt2"), "dump", "badging", str(apk)], check=True, capture_output=True, text=True).stdout
    assert "name='ir.dicode.ping.fdroid'" in manifest, "Android application ID changed"
    assert "versionName='4.9.91'" in manifest and "versionCode='45991000'" in manifest, "APK version mismatch"
    assert "targetSdkVersion:'36'" in manifest, "APK targets a preview SDK"
    subprocess.run([str(tools / "zipalign"), "-c", "-P", "16", "-v", "4", str(apk)], check=True, stdout=subprocess.DEVNULL)
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            parts = name.split('/')
            if len(parts) == 3 and parts[0] == 'lib' and name.endswith('.so'):
                verify_elf(archive.read(name), parts[1], name)
        for item in json.loads(pathlib.Path("scripts/runtime-pins-4.9.91.json").read_text())["android_geodata"]:
            content = archive.read("assets/" + item["name"])
            assert hashlib.sha256(content).hexdigest() == item["sha256"], "Missing or altered Android Geo asset: " + item["name"]
        for notice in ["NOTICE.txt", "LICENSE-GPL-3.0.txt", "LICENSE-CC-BY-SA-4.0.txt"]:
            assert "assets/routing-data/" + notice in archive.namelist(), "Routing data attribution is missing"
        packaged = [a for a in abis if a != "universal"] if abi == "universal" else [abi]
        for architecture in packaged:
            storage = archive.read(f"lib/{architecture}/libmmkv.so")
            assert storage[:4] == b"\x7fELF" and storage[4] == (2 if architecture in ("arm64-v8a", "x86_64") else 1), "Storage native library missing or architecture mismatch"
            assert f"lib/{architecture}/libsingbox.so" not in archive.namelist(), "Removed runtime was bundled"
            fox = archive.read(f"lib/{architecture}/libdicodefox.so")
            assert fox[:4] == b"\x7fELF" and fox[4] == (2 if architecture in ("arm64-v8a", "x86_64") else 1), "Fox helper architecture mismatch"
        for notice in ["LICENSE-FoxyVPN.txt", "LICENSE-Go.txt", "LICENSE-DicodePing.txt"]:
            assert "assets/fox/" + notice in archive.namelist(), "Fox license is missing: " + notice
    print("Verified signed upgrade and native core:", apk.name)
