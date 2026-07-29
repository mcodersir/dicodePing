from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "app" / "src" / "main" / "res" / "font"
FONT_NAMES = ("regular", "medium", "bold")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that the optimized APK contains the exact bundled Vazirmatn font payloads."
    )
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    apk = args.apk.resolve()
    if not apk.is_file():
        print(f"APK was not found: {apk}", file=sys.stderr)
        return 1

    expected: dict[str, str] = {}
    for weight in FONT_NAMES:
        source = FONT_DIR / f"vazirmatn_{weight}.ttf"
        if not source.is_file():
            print(f"Generated font source is missing: {source}", file=sys.stderr)
            return 1
        expected[weight] = sha256_bytes(source.read_bytes())

    with zipfile.ZipFile(apk) as archive:
        candidates = {
            name: sha256_bytes(archive.read(name))
            for name in archive.namelist()
            if name.lower().endswith((".ttf", ".otf"))
        }

    missing = {
        weight: digest
        for weight, digest in expected.items()
        if digest not in candidates.values()
    }
    if missing:
        print("APK does not contain the exact bundled Vazirmatn font payloads.", file=sys.stderr)
        print(f"Missing weights: {', '.join(sorted(missing))}", file=sys.stderr)
        print(f"APK font entries inspected: {', '.join(sorted(candidates)) or '(none)'}", file=sys.stderr)
        return 1

    print(
        "Verified APK Vazirmatn fonts by content hash: "
        + ", ".join(f"{weight}={digest[:12]}" for weight, digest in expected.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
