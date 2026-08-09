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
    parser = argparse.ArgumentParser(description="Verify dicodePing release metadata.")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    stable = extract(ROOT / "dicodeping/constants.py", r'(?m)^VERSION\s*=\s*"([^"]+)"', "stable version")
    release = extract(ROOT / "dicodeping/constants.py", r'(?m)^RELEASE_VERSION\s*=\s*"([^"]+)"', "release version")
    python_expected = release.replace("-", "").replace("rc.", "rc")
    checks = {
        "python package": (
            extract(ROOT / "dicodeping/__init__.py", r'(?m)^__version__\s*=\s*"([^"]+)"', "version"),
            python_expected,
        ),
        "Windows builder": (
            extract(ROOT / "tools/build_windows.py", r'(?m)^APP_VERSION\s*=\s*"([^"]+)"', "version"),
            release,
        ),
        "Linux builder": (
            extract(ROOT / "tools/build_linux.py", r'(?m)^APP_VERSION\s*=\s*"([^"]+)"', "version"),
            release,
        ),
        "macOS builder": (
            extract(ROOT / "tools/build_macos.py", r'(?m)^APP_VERSION\s*=\s*"([^"]+)"', "version"),
            release,
        ),
        "Android": (
            extract(ROOT / "dicodePing_android/app/build.gradle.kts", r'(?m)^\s*versionName\s*=\s*"([^"]+)"', "version"),
            release,
        ),
        "Windows metadata": (
            extract(ROOT / "tools/windows_version_info.txt", r"StringStruct\('ProductVersion',\s*'([0-9]+\.[0-9]+\.[0-9]+)\.0'\)", "version"),
            stable,
        ),
    }
    mismatches = {
        name: {"actual": actual, "expected": expected}
        for name, (actual, expected) in checks.items()
        if actual != expected
    }
    if mismatches:
        print(f"Version mismatches: {mismatches}")
        return 1
    if release == stable and re.search(r'(?m)^RC_VERSION\s*=', (ROOT / "tools/build_windows.py").read_text(encoding="utf-8")):
        print("Stable release builders must not define an RC suffix.")
        return 1
    if args.tag and args.tag != f"v{release}":
        print(f"Tag {args.tag!r} does not match v{release}")
        return 1
    print(f"dicodePing versions are consistent: package={python_expected}, release={release}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
