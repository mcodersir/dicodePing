from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_VERSION = "1.6.0"
APP_NAME = "dicodePing"


def run(command, cwd):
    subprocess.run(command, cwd=cwd, check=True)


def build(*, skip_install=False, skip_core=False):
    if os.name != "nt":
        raise RuntimeError("Windows builder must run on Windows")
    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    if not skip_install:
        run([python, "-m", "pip", "install", "-r", "requirements-build.txt"], root)
    if not skip_core:
        run([python, "-m", "tools.prepare_core"], root)
    release = root / "release"
    release.mkdir(exist_ok=True)
    run([python, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", APP_NAME, "--collect-submodules", "dicodeping", str(root / "app_rc3.py")], root)
    output = release / f"{APP_NAME}-v{APP_VERSION}-windows.exe"
    shutil.copy2(root / "dist" / f"{APP_NAME}.exe", output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-core", action="store_true")
    args = parser.parse_args()
    build(skip_install=args.skip_install, skip_core=args.skip_core)
