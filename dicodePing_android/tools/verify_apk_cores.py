#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

REQUIRED = ("libgojni.so", "libaether.so", "libusque.so")
ABIS = {"arm64-v8a": 183, "x86_64": 62}
MANIFEST = "assets/bundled_cores.json"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_apk_cores.py <apk>")

    apk = Path(sys.argv[1])
    if not apk.is_file():
        raise SystemExit(f"APK missing: {apk}")

    with zipfile.ZipFile(apk) as zf:
        names = set(zf.namelist())
        if MANIFEST not in names:
            raise SystemExit(f"Missing bundled-core manifest: {MANIFEST}")
        manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
        if manifest.get("release") != "1.9.0-rc.15":
            raise SystemExit(f"Wrong bundled-core release manifest: {manifest.get('release')!r}")

        declared = {
            (entry.get("abi"), entry.get("file")): entry
            for entry in manifest.get("entries", [])
            if isinstance(entry, dict)
        }
        total = 0
        for abi, expected_machine in ABIS.items():
            for lib in REQUIRED:
                name = f"lib/{abi}/{lib}"
                if name not in names:
                    raise SystemExit(f"Missing bundled core: {name}")
                payload = zf.read(name)
                info = zf.getinfo(name)
                if len(payload) < 500_000:
                    raise SystemExit(f"Bundled core unexpectedly small: {name} ({len(payload)})")
                if payload[:4] != b"\x7fELF":
                    raise SystemExit(f"Bundled core is not ELF: {name}")
                machine = int.from_bytes(payload[18:20], "little")
                if machine != expected_machine:
                    raise SystemExit(
                        f"Bundled core ABI mismatch: {name}; expected machine {expected_machine}, got {machine}"
                    )
                total += len(payload)

                if lib in {"libaether.so", "libusque.so"}:
                    entry = declared.get((abi, lib))
                    if not entry:
                        raise SystemExit(f"Core manifest does not declare {abi}/{lib}")
                    digest = hashlib.sha256(payload).hexdigest()
                    if entry.get("sha256") != digest or entry.get("bytes") != len(payload):
                        raise SystemExit(f"Core manifest hash/size mismatch for {abi}/{lib}")

                print(
                    f"{name}: raw={info.file_size} compressed={info.compress_size} "
                    f"elfMachine={machine}"
                )

        if any(name.startswith("lib/armeabi-v7a/") or name.startswith("lib/x86/") for name in names):
            raise SystemExit("Unexpected 32-bit native libraries are present in the public APK")

        print(f"Bundled native core payload: {total / 1024 / 1024:.1f} MiB")
        print(f"Verified APK: {apk} ({apk.stat().st_size / 1024 / 1024:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
