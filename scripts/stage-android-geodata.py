#!/usr/bin/env python3
"""Stage immutable, checksum-verified routing data required by the Android APK."""
import hashlib
import json
import pathlib
import urllib.request

root = pathlib.Path(__file__).resolve().parent.parent
pins = json.loads((root / "scripts/runtime-pins-4.9.3.json").read_text())
output = root / "apps/android/app/src/main/assets"
output.mkdir(parents=True, exist_ok=True)
for item in pins["android_geodata"]:
    with urllib.request.urlopen(item["url"], timeout=90) as response:
        content = response.read()
    if hashlib.sha256(content).hexdigest() != item["sha256"]:
        raise RuntimeError("Android Geo database SHA-256 mismatch: " + item["name"])
    temporary = output / (item["name"] + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(output / item["name"])
    print("Verified Android routing data:", item["name"], len(content))
