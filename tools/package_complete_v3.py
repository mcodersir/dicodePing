from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# Support both invocation styles:
#   python tools/package_complete_v3.py
#   python -m tools.package_complete_v3
# When a script inside tools/ is executed directly, Python puts tools/ rather
# than the project root at sys.path[0]. Add the project root explicitly before
# importing the tools package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_runtime_assets import (
    ROOT,
    RUNTIME,
    ANDROID_AAR,
    XRAY_ASSETS,
    SING_BOX_ASSETS,
    WINTUN_VERSION,
    WINTUN_SHA256,
    ANDROID_AAR_SHA256,
    verify,
)

RELEASE = "3.0.0-pre.6"
OUTPUT_NAME = f"dicodePing-{RELEASE}-complete.zip"
EXCLUDED_DIRS = {".git", "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".part"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_runtime_files() -> dict[str, str]:
    expected: dict[str, str] = {}
    for name, digest in XRAY_ASSETS.items():
        expected[f"runtime_assets/{name}"] = digest
    expected[f"runtime_assets/wintun-{WINTUN_VERSION}.zip"] = WINTUN_SHA256
    for name, digest in SING_BOX_ASSETS.items():
        expected[f"runtime_assets/{name}"] = digest
    expected[str(ANDROID_AAR.relative_to(ROOT)).replace("\\", "/")] = ANDROID_AAR_SHA256
    return expected


def verify_runtime_bundle() -> None:
    missing: list[str] = []
    for rel, digest in expected_runtime_files().items():
        path = ROOT / rel
        if not verify(path, digest):
            missing.append(rel)
    if missing:
        raise RuntimeError(
            "Cannot create the complete package. These pinned runtime files are missing or invalid:\n- "
            + "\n- ".join(missing)
            + "\nRun REPAIR_V3_RUNTIME.bat first."
        )


def included_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.is_dir():
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.name == OUTPUT_NAME or path.name == OUTPUT_NAME + ".sha256":
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def verify_zip_runtime_entries(output: Path) -> None:
    prefix = f"dicodePing-{RELEASE}/"
    expected = expected_runtime_files()
    with zipfile.ZipFile(output, "r") as zf:
        names = set(zf.namelist())
        for rel, digest in expected.items():
            entry = prefix + rel
            if entry not in names:
                raise RuntimeError(f"complete ZIP is missing runtime entry: {rel}")
            h = hashlib.sha256()
            with zf.open(entry, "r") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            actual = h.hexdigest()
            if actual.lower() != digest.lower():
                raise RuntimeError(f"runtime SHA-256 mismatch inside ZIP: {rel}: {actual}")


def verify_extracted_bundle(output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="dicodeping-v3-verify-") as temp_dir:
        temp = Path(temp_dir)
        with zipfile.ZipFile(output, "r") as zf:
            zf.extractall(temp)
        root = temp / f"dicodePing-{RELEASE}"
        if not root.is_dir():
            raise RuntimeError("complete ZIP has an invalid top-level directory")
        for rel, digest in expected_runtime_files().items():
            path = root / rel
            if not path.is_file():
                raise RuntimeError(f"extracted ZIP is missing runtime file: {rel}")
            if sha256(path).lower() != digest.lower():
                raise RuntimeError(f"extracted runtime SHA-256 mismatch: {rel}")
        required = [
            "app.py",
            "corehost/dicodePing.CoreHost.csproj",
            "runtime_assets/RUNTIME_ASSETS.lock.json",
            "PREPARE_V3_RUNTIME.bat",
            "README.md",
        ]
        for rel in required:
            if not (root / rel).is_file():
                raise RuntimeError(f"extracted ZIP is missing required project file: {rel}")


def build_complete_zip(verify_output: bool) -> Path:
    verify_runtime_bundle()
    dist = ROOT / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    output = dist / OUTPUT_NAME
    output.unlink(missing_ok=True)
    prefix = f"dicodePing-{RELEASE}"
    files = included_files()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            zf.write(path, f"{prefix}/{rel}")

    verify_zip_runtime_entries(output)
    if verify_output:
        verify_extracted_bundle(output)

    digest = sha256(output)
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print("Complete offline package created and verified:")
    print(output)
    print(f"SHA-256: {digest}")
    print("All pinned Xray, sing-box, Wintun and Android runtime files are included.")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the self-contained dicodePing Version 3 package")
    parser.add_argument("--verify-output", action="store_true", help="extract the generated ZIP and verify its runtime set")
    args = parser.parse_args()
    try:
        build_complete_zip(args.verify_output)
        return 0
    except Exception as exc:
        print(f"Complete package creation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
