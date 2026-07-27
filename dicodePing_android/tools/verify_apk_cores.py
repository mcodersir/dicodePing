#!/usr/bin/env python3
from __future__ import annotations
import sys, zipfile
from pathlib import Path
REQUIRED = ("libgojni.so", "libaether.so", "libusque.so")
ABIS = ("arm64-v8a", "x86_64")

def main() -> int:
    apk = Path(sys.argv[1])
    if not apk.is_file(): raise SystemExit(f"APK missing: {apk}")
    with zipfile.ZipFile(apk) as zf:
        names=set(zf.namelist())
        total=0
        for abi in ABIS:
            for lib in REQUIRED:
                name=f"lib/{abi}/{lib}"
                if name not in names: raise SystemExit(f"Missing bundled core: {name}")
                info=zf.getinfo(name)
                if info.file_size < 500_000: raise SystemExit(f"Bundled core unexpectedly small: {name} ({info.file_size})")
                total += info.file_size
                print(f"{name}: raw={info.file_size} compressed={info.compress_size}")
        print(f"Bundled native core payload: {total/1024/1024:.1f} MiB; APK: {apk.stat().st_size/1024/1024:.1f} MiB")
    return 0
if __name__ == '__main__': raise SystemExit(main())
