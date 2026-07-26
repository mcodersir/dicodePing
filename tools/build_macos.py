from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_VERSION = "1.9.0"
RC_VERSION = "rc.1"
APP_NAME = "dicodePing"


def run(command: list[str], cwd: Path) -> None:
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def build(*, skip_install: bool = False, skip_core: bool = False) -> Path:
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

    core, assets = root / "core", root / "assets"
    icon = assets / "app.icns"
    if not icon.exists():
        iconset = root / "build" / "dicodePing.iconset"
        shutil.rmtree(iconset, ignore_errors=True)
        iconset.mkdir(parents=True)
        for size in (16, 32, 128, 256, 512):
            run(["sips", "-z", str(size), str(size), str(assets / "app.png"), "--out", str(iconset / f"icon_{size}x{size}.png")], root)
            run(["sips", "-z", str(size * 2), str(size * 2), str(assets / "app.png"), "--out", str(iconset / f"icon_{size}x{size}@2x.png")], root)
        run(["iconutil", "-c", "icns", str(iconset), "-o", str(icon)], root)
    separator = os.pathsep
    command = [
        python, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME, "--icon", str(icon),
        "--hidden-import", "PySide6.QtSvg", "--collect-submodules", "dicodeping",
        "--add-data", f"{assets}{separator}assets",
        "--add-binary", f"{core / 'xray'}{separator}core",
        "--add-binary", f"{core / 'aether'}{separator}core",
        "--add-binary", f"{core / 'usque'}{separator}core",
        "--add-data", f"{core / 'bundled-cores.json'}{separator}core",
        str(root / "app_rc3.py"),
    ]
    run(command, root)
    app = root / "dist" / f"{APP_NAME}.app"
    if not app.is_dir():
        raise FileNotFoundError(f"PyInstaller app bundle not found: {app}")
    architecture = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
    release = root / "release"
    release.mkdir(exist_ok=True)
    output = release / f"{APP_NAME}-v{APP_VERSION}-{RC_VERSION}-macos-{architecture}.dmg"
    output.unlink(missing_ok=True)
    run([
        "hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(app),
        "-ov", "-format", "UDZO", str(output),
    ], root)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
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
