from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract(path: Path, pattern: str, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Could not read {label} from {path.relative_to(ROOT)}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify dicodePing version consistency.")
    parser.add_argument("--tag", default="", help="Optional release tag, for example v0.1.2")
    args = parser.parse_args()

    versions = {
        "python package": extract(ROOT / "dicodeping" / "__init__.py", r'__version__\s*=\s*"([^"]+)"', "version"),
        "constants": extract(ROOT / "dicodeping" / "constants.py", r'VERSION\s*=\s*"([^"]+)"', "version"),
        "Windows builder": extract(ROOT / "tools" / "build_windows.py", r'APP_VERSION\s*=\s*"([^"]+)"', "version"),
        "Android": extract(ROOT / "dicodePing_android" / "app" / "build.gradle.kts", r'versionName\s*=\s*"([^"]+)"', "version"),
        "Windows metadata": extract(ROOT / "tools" / "windows_version_info.txt", r"StringStruct\('ProductVersion',\s*'([0-9]+\.[0-9]+\.[0-9]+)\.0'\)", "version"),
    }

    expected = next(iter(versions.values()))
    mismatches = {name: value for name, value in versions.items() if value != expected}
    if mismatches:
        print(f"Expected all versions to be {expected}; mismatches: {mismatches}")
        return 1

    if args.tag and args.tag != f"v{expected}":
        print(f"Tag {args.tag!r} does not match version v{expected}")
        return 1

    print(f"dicodePing version is consistent: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
