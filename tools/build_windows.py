from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_VERSION = "2.0.5"
APP_NAME = "dicodePing"


def run(command: list[str], cwd: Path) -> None:
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def build(*, skip_install: bool = False, skip_core: bool = False) -> Path:
    """Build the same portable one-file Windows artifact used by v1.8.0-rc.4."""
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

    run([python, "-m", "tools.prepare_vazirmatn"], root)

    if not skip_core:
        print("[2/4] Preparing and verifying the official Xray core...", flush=True)
        run([python, "-m", "tools.prepare_core"], root)
        run([python, "-m", "tools.prepare_optional_cores"], root)
    else:
        print("[2/4] Xray preparation skipped.", flush=True)

    print("[3/4] Building the legacy-style portable Windows executable...", flush=True)
    assets = root / "assets"
    core = root / "core"
    entrypoint = root / "app_v200.py"
    generated_spec_dir = root / "build" / "windows-spec"
    generated_spec_dir.mkdir(parents=True, exist_ok=True)

    font_files = [assets / "fonts" / f"Vazirmatn-{weight}.ttf" for weight in ("Regular", "Medium", "Bold")]
    required = [
        entrypoint,
        assets / "app.ico",
        root / "tools" / "windows_version_info.txt",
        core / "xray.exe",
        core / "wintun.dll",
        core / "aether.exe",
        core / "usque.exe",
    ]
    required.extend(font_files)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required Windows build files:\n- " + "\n- ".join(missing))

    separator = os.pathsep
    command = [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--specpath",
        str(generated_spec_dir),
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
        "--add-binary",
        f"{core / 'xray.exe'}{separator}core",
        "--add-binary",
        f"{core / 'wintun.dll'}{separator}core",
        "--add-binary",
        f"{core / 'aether.exe'}{separator}core",
        "--add-binary",
        f"{core / 'usque.exe'}{separator}core",
    ]
    for data_name in ("geoip.dat", "geosite.dat"):
        path = core / data_name
        if path.exists():
            command.extend(["--add-data", f"{path}{separator}core"])
    command.append(str(entrypoint))
    run(command, root)

    print("[4/4] Preparing the release output...", flush=True)
    built_exe = root / "dist" / f"{APP_NAME}.exe"
    if not built_exe.exists():
        raise FileNotFoundError(f"PyInstaller completed but output was not found: {built_exe}")

    release_dir = root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    output = release_dir / f"{APP_NAME}-v{APP_VERSION}-windows-x64.exe"
    shutil.copy2(built_exe, output)
    print(f"Windows build completed: {output}", flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable dicodePing Windows EXE.")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-core", action="store_true")
    args = parser.parse_args()
    try:
        build(skip_install=args.skip_install, skip_core=args.skip_core)
    except subprocess.CalledProcessError as exc:
        print(f"Build command failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"Windows build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
