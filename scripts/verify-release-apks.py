#!/usr/bin/env python3
"""Check upgrade identity, signing certificate and native sing-box packaging."""
import os, pathlib, re, subprocess, zipfile, json, hashlib
root = pathlib.Path("dist-android")
tools = pathlib.Path(os.environ["ANDROID_HOME"]) / "build-tools" / "37.0.0"
expected_cert = "0a483317ee0bd0e2aea48d2be72c30f206d3cceb3f178ea18ca22a17d6cdfcc0"
abis = {"universal": 0, "arm64-v8a": 1, "armeabi-v7a": 2, "x86_64": 3, "x86": 4}
for abi, suffix in abis.items():
    apk = root / f"DicodePing-4.9.3-{abi}.apk"
    signer = subprocess.run([str(tools / "apksigner"), "verify", "--print-certs", str(apk)], check=True, capture_output=True, text=True).stdout
    certs = re.findall(r"certificate SHA-256 digest: ([0-9a-fA-F]+)", signer)
    assert certs and all(c.lower() == expected_cert for c in certs), "APK signing identity changed"
    manifest = subprocess.run([str(tools / "aapt2"), "dump", "badging", str(apk)], check=True, capture_output=True, text=True).stdout
    assert "name='ir.dicode.ping.fdroid'" in manifest, "Android application ID changed"
    assert "versionName='4.9.3'" in manifest and "versionCode='45930000'" in manifest, "APK version mismatch"
    assert "targetSdkVersion:'36'" in manifest, "APK targets a preview SDK"
    with zipfile.ZipFile(apk) as archive:
        for item in json.loads(pathlib.Path("scripts/runtime-pins-4.9.3.json").read_text())["android_geodata"]:
            content = archive.read("assets/" + item["name"])
            assert hashlib.sha256(content).hexdigest() == item["sha256"], "Missing or altered Android Geo asset: " + item["name"]
        for notice in ["NOTICE.txt", "LICENSE-GPL-3.0.txt", "LICENSE-CC-BY-SA-4.0.txt"]:
            assert "assets/routing-data/" + notice in archive.namelist(), "Routing data attribution is missing"
        packaged = [a for a in abis if a != "universal"] if abi == "universal" else [abi]
        for architecture in packaged:
            native = archive.read(f"lib/{architecture}/libsingbox.so")
            assert native[:4] == b"\x7fELF" and native[4] == (2 if architecture in ("arm64-v8a", "x86_64") else 1), "Native core architecture mismatch"
            fox = archive.read(f"lib/{architecture}/libdicodefox.so")
            assert fox[:4] == b"\x7fELF" and fox[4] == (2 if architecture in ("arm64-v8a", "x86_64") else 1), "Fox helper architecture mismatch"
        for notice in ["LICENSE-FoxyVPN.txt", "LICENSE-Go.txt", "LICENSE-DicodePing.txt"]:
            assert "assets/fox/" + notice in archive.namelist(), "Fox license is missing: " + notice
    print("Verified signed upgrade and native core:", apk.name)
