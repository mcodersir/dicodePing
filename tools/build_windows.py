from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_VERSION = "1.7.0"
APP_NAME = "dicodePing"


def run(command: list[str], cwd: Path) -> None:
    printable = subprocess.list2cmdline(command)
    print(f"> {printable}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def build(*, skip_install: bool = False, skip_core: bool = False) -> Path:
    if os.name != "nt":
        raise RuntimeError("The Windows EXE builder must be run on Windows.")

    root = Path(__file__).resolve().parents[1]
    python = sys.executable

    if not skip_install:
        print("[1/4] Installing build dependencies...", flush=True)
        run([python, "-m", "pip", "install", "--upgrade", "pip"], root)
        run([python, "-m", "pip", "install", "-r", "requirements-build.txt"], root)
    else:
        print("[1/4] Dependency installation skipped.", flush=True)

    if not skip_core:
        print("[2/4] Preparing the official Xray core...", flush=True)
        run([python, "-m", "tools.prepare_core"], root)
    else:
        print("[2/4] Xray preparation skipped.", flush=True)

    print("[3/4] Building the Windows executable...", flush=True)

    assets = root / "assets"
    core = root / "core"
    entrypoint = root / "app_rc3.py"

    required_paths = [
        root / "requirements-build.txt",
        entrypoint,
        root / "app.py",
        root / "dicodeping" / "rc2_core.py",
        root / "dicodeping" / "rc2_runtime.py",
        root / "dicodeping" / "rc3_core.py",
        root / "dicodeping" / "rc3_runtime.py",
        root / "dicodeping" / "rc4_core.py",
        root / "dicodeping" / "rc4_runtime.py",
        root / "dicodeping" / "rc5_core.py",
        root / "dicodeping" / "rc5_runtime.py",
        root / "dicodeping" / "rc6_runtime.py",
        root / "dicodeping" / "rc7_core.py",
        root / "dicodeping" / "rc7_runtime.py",
        root / "dicodeping" / "rc8_core.py",
        root / "dicodeping" / "rc8_runtime.py",
        root / "dicodeping" / "rc9_core.py",
        assets,
        assets / "app.ico",
        root / "tools" / "windows_version_info.txt",
        core / "xray.exe",
        core / "wintun.dll",
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required build files:\n- " + "\n- ".join(missing))

    separator = os.pathsep
    command = [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--uac-admin",
        "--name",
        APP_NAME,
        "--icon",
        str(assets / "app.ico"),
        "--version-file",
        str(root / "tools" / "windows_version_info.txt"),
        "--hidden-import",
        "PySide6.QtSvg",
        "--collect-submodules",
        "dicodeping",
        "--add-data",
        f"{assets}{separator}assets",
    ]

    optional_files = (
        (core / "xray.exe", "--add-binary"),
        (core / "geoip.dat", "--add-data"),
        (core / "geosite.dat", "--add-data"),
        (core / "wintun.dll", "--add-binary"),
    )
    for path, switch in optional_files:
        if path.exists():
            command.extend([switch, f"{path}{separator}core"])

    command.append(str(entrypoint))
    run(command, root)

    print("[4/4] Preparing the release output...", flush=True)
    built_exe = root / "dist" / f"{APP_NAME}.exe"
    if not built_exe.exists():
        raise FileNotFoundError(f"PyInstaller completed but output was not found: {built_exe}")

    release_dir = root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    output = release_dir / f"{APP_NAME}-v{APP_VERSION}-windows.exe"
    shutil.copy2(built_exe, output)
    print(f"Build completed: {output}", flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dicodePing for Windows.")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-core", action="store_true")
    args = parser.parse_args()

    try:
        build(skip_install=args.skip_install, skip_core=args.skip_core)
    except subprocess.CalledProcessError as exc:
        print(f"Build command failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
