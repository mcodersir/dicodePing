from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

APP_VERSION = "1.6.0"
RC_VERSION = "rc.4"
APP_NAME = "dicodePing"


def run(command: list[str], cwd: Path) -> None:
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def build(*, skip_install: bool = False, skip_core: bool = False) -> Path:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("The Linux builder must run on Linux.")

    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    if not skip_install:
        run([python, "-m", "pip", "install", "--upgrade", "pip"], root)
        run([python, "-m", "pip", "install", "-r", "requirements-build.txt"], root)
    if not skip_core:
        run([python, "-m", "tools.prepare_core"], root)

    core = root / "core"
    assets = root / "assets"
    entrypoint = root / "app_rc3.py"
    required = [entrypoint, core / "xray", assets / "app.png", root / "packaging" / "linux" / "run-dicodePing.sh"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Linux build files:\n- " + "\n- ".join(missing))

    separator = os.pathsep
    spec_dir = root / "build" / "linux-spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    command = [
        python, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", APP_NAME, "--specpath", str(spec_dir), "--icon", str(assets / "app.png"),
        "--hidden-import", "PySide6.QtSvg", "--collect-submodules", "dicodeping",
        "--add-data", f"{assets}{separator}assets",
        "--add-binary", f"{core / 'xray'}{separator}core",
    ]
    for data_name in ("geoip.dat", "geosite.dat"):
        path = core / data_name
        if path.exists():
            command.extend(["--add-data", f"{path}{separator}core"])
    command.append(str(entrypoint))
    run(command, root)

    built = root / "dist" / APP_NAME
    if not built.exists():
        raise FileNotFoundError(f"PyInstaller output was not found: {built}")
    built.chmod(0o755)

    architecture = "arm64" if platform.machine().lower() in {"aarch64", "arm64"} else "x86_64"
    bundle_name = f"{APP_NAME}-v{APP_VERSION}-{RC_VERSION}-linux-{architecture}"
    staging = root / "build" / bundle_name
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copy2(built, staging / APP_NAME)
    shutil.copy2(root / "packaging" / "linux" / "run-dicodePing.sh", staging / "run-dicodePing.sh")
    shutil.copy2(root / "packaging" / "linux" / "README-LINUX.txt", staging / "README-LINUX.txt")
    shutil.copy2(root / "packaging" / "linux" / "dicodePing.desktop", staging / "dicodePing.desktop")
    shutil.copy2(assets / "app.png", staging / "app.png")
    (staging / APP_NAME).chmod(0o755)
    (staging / "run-dicodePing.sh").chmod(0o755)

    release = root / "release"
    release.mkdir(parents=True, exist_ok=True)
    output = release / f"{bundle_name}.tar.gz"
    with tarfile.open(output, "w:gz") as archive:
        archive.add(staging, arcname=bundle_name)
    print(f"Linux build completed: {output}", flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable dicodePing Linux bundle.")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-core", action="store_true")
    args = parser.parse_args()
    try:
        build(skip_install=args.skip_install, skip_core=args.skip_core)
        return 0
    except Exception as exc:
        print(f"Linux build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
