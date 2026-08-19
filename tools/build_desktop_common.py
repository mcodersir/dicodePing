from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "dicodePing"
APP_VERSION = "3.0.0-pre.6"
ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print(">", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def prepare_build(skip_install: bool) -> Path:
    if not skip_install:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        run([sys.executable, "-m", "pip", "install", "-r", "requirements-build.txt"])
    run([sys.executable, "-m", "tools.prepare_vazirmatn"])
    run([sys.executable, "-m", "tools.prepare_engine"])
    rid = "win-x64" if os.name == "nt" else ("osx-arm64" if sys.platform == "darwin" and __import__("platform").machine().lower() in {"arm64","aarch64"} else "osx-x64" if sys.platform == "darwin" else "linux-arm64" if __import__("platform").machine().lower() in {"arm64","aarch64"} else "linux-x64")
    engine = ROOT / "build" / "engine" / rid
    if not engine.exists():
        raise FileNotFoundError(engine)
    return engine


def pyinstaller_base(engine: Path, *, windowed: bool = True) -> list[str]:
    sep = os.pathsep
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed" if windowed else "--console", "--name", APP_NAME,
        "--hidden-import", "PySide6.QtSvg", "--collect-submodules", "dicodeping",
        "--collect-data", "certifi", "--add-data", f"{ROOT / 'assets'}{sep}assets",
        "--add-data", f"{engine}{sep}engine",
    ]
    return command
