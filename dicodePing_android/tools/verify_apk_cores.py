#!/usr/bin/env python3
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ABIS = {"arm64-v8a": 183, "armeabi-v7a": 40, "x86_64": 62}
NATIVE_NAMES = ("libgojni.so", "libv2ray.so")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_apk_cores.py <apk>")
    apk = Path(sys.argv[1])
    if not apk.is_file():
        raise SystemExit(f"APK missing: {apk}")

    with zipfile.ZipFile(apk) as zf:
        names = set(zf.namelist())
        total = 0
        for abi, expected_machine in ABIS.items():
            candidates = [f"lib/{abi}/{name}" for name in NATIVE_NAMES if f"lib/{abi}/{name}" in names]
            if not candidates:
                raise SystemExit(f"Missing Android runtime for ABI: {abi}")
            for name in candidates:
                payload = zf.read(name)
                if len(payload) < 500_000:
                    raise SystemExit(f"Android runtime unexpectedly small: {name} ({len(payload)})")
                if payload[:4] != b"\x7fELF":
                    raise SystemExit(f"Android runtime is not ELF: {name}")
                machine = int.from_bytes(payload[18:20], "little")
                if machine != expected_machine:
                    raise SystemExit(
                        f"Android runtime ABI mismatch: {name}; expected machine {expected_machine}, got {machine}"
                    )
                total += len(payload)
                print(f"{name}: {len(payload)} bytes, elfMachine={machine}")

        print(f"Verified Android runtime payload: {total / 1024 / 1024:.1f} MiB")
        print(f"Verified APK: {apk} ({apk.stat().st_size / 1024 / 1024:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
