from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_VERSION = "1.9.0"
RC_VERSION = "rc.17"
APP_NAME = "dicodePing"
BUNDLE_ID = "ir.dicode.dicodePing"


def run(command: list[str], cwd: Path) -> None:
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _build_icon(root: Path) -> Path:
    assets = root / "assets"
    icon_root = root / "build" / "macos-icon"
    iconset = icon_root / f"{APP_NAME}.iconset"
    icon = icon_root / f"{APP_NAME}.icns"
    shutil.rmtree(icon_root, ignore_errors=True)
    iconset.mkdir(parents=True)
    for size in (16, 32, 128, 256, 512):
        run([
            "sips", "-z", str(size), str(size), str(assets / "app.png"),
            "--out", str(iconset / f"icon_{size}x{size}.png"),
        ], root)
        run([
            "sips", "-z", str(size * 2), str(size * 2), str(assets / "app.png"),
            "--out", str(iconset / f"icon_{size}x{size}@2x.png"),
        ], root)
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(icon)], root)
    return icon


def build(*, skip_install: bool = False, skip_core: bool = False) -> Path:
    """Build an unsigned portable macOS app and place it in a DMG."""
    if sys.platform != "darwin":
        raise RuntimeError("The macOS builder must run on macOS.")

    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    if not skip_install:
        run([python, "-m", "pip", "install", "--upgrade", "pip"], root)
        run([python, "-m", "pip", "install", "-r", "requirements-build.txt"], root)
    if not skip_core:
        run([python, "-m", "tools.prepare_core"], root)
        run([python, "-m", "tools.prepare_optional_cores"], root)

    core = root / "core"
    assets = root / "assets"
    entrypoint = root / "app_v190_rc17.py"
    required = [entrypoint, assets / "app.png", core / "xray", core / "aether", core / "usque"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing macOS build files:\n- " + "\n- ".join(missing))

    icon = _build_icon(root)
    separator = os.pathsep
    spec_dir = root / "build" / "macos-spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    command = [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--specpath",
        str(spec_dir),
        "--icon",
        str(icon),
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--hidden-import",
        "PySide6.QtSvg",
        "--collect-submodules",
        "dicodeping",
        "--add-data",
        f"{assets}{separator}assets",
        "--add-binary",
        f"{core / 'xray'}{separator}core",
        "--add-binary",
        f"{core / 'aether'}{separator}core",
        "--add-binary",
        f"{core / 'usque'}{separator}core",
    ]
    for data_name in ("geoip.dat", "geosite.dat"):
        path = core / data_name
        if path.exists():
            command.extend(["--add-data", f"{path}{separator}core"])
    command.append(str(entrypoint))
    run(command, root)

    app = root / "dist" / f"{APP_NAME}.app"
    if not app.is_dir():
        raise FileNotFoundError(f"PyInstaller app bundle was not found: {app}")

    architecture = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
    bundle_name = f"{APP_NAME}-v{APP_VERSION}-{RC_VERSION}-macos-{architecture}"
    dmg_root = root / "build" / f"{bundle_name}-dmg"
    shutil.rmtree(dmg_root, ignore_errors=True)
    dmg_root.mkdir(parents=True)
    shutil.copytree(app, dmg_root / f"{APP_NAME}.app", symlinks=True)
    (dmg_root / "Applications").symlink_to("/Applications")

    release = root / "release"
    release.mkdir(parents=True, exist_ok=True)
    output = release / f"{bundle_name}.dmg"
    output.unlink(missing_ok=True)
    run([
        "hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(dmg_root),
        "-ov", "-format", "UDZO", str(output),
    ], root)
    print(f"macOS build completed: {output}", flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable dicodePing macOS DMG.")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-core", action="store_true")
    args = parser.parse_args()
    try:
        print(build(skip_install=args.skip_install, skip_core=args.skip_core))
        return 0
    except Exception as exc:
        print(f"macOS build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
