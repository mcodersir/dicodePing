from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP_VERSION = "3.0.0-rc.1"
APP_NAME = "dicodePing"
BUNDLE_ID = "ir.dicode.dicodePing"
DMG_CREATE_ATTEMPTS = 6
DMG_RETRY_DELAYS = (2, 4, 7, 11, 16, 24)


def run(command: list[str], cwd: Path) -> None:
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _run_captured(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    return result


def _retryable_hdiutil_failure(result: subprocess.CompletedProcess[str]) -> bool:
    message = f"{result.stdout}\n{result.stderr}".lower()
    retryable_markers = (
        "resource busy",
        "temporarily unavailable",
        "operation timed out",
        "couldn't unmount",
        "could not unmount",
        "device busy",
        "eagain",
        "ebusy",
    )
    return any(marker in message for marker in retryable_markers)


def _sync_filesystem() -> None:
    try:
        os.sync()
    except AttributeError:
        subprocess.run(["sync"], check=False)


def _verify_dmg(path: Path, root: Path) -> bool:
    result = _run_captured(["hdiutil", "verify", str(path)], root)
    return result.returncode == 0


def _create_dmg_with_retry(
    *,
    source_root: Path,
    output: Path,
    volume_name: str,
    root: Path,
) -> None:
    """Create and verify a DMG while tolerating transient DiskImages EBUSY failures.

    GitHub's Intel macOS runners can briefly keep a freshly copied/signed app
    bundle busy.  Each attempt therefore uses a brand-new staging directory and
    output path.  A completed image is verified before it replaces the public
    release path, so an interrupted attempt can never leave a corrupt asset.
    """

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    build_root = root / "build"
    build_root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    for attempt in range(1, DMG_CREATE_ATTEMPTS + 1):
        with tempfile.TemporaryDirectory(prefix="dicodeping-dmg-", dir=build_root) as temp_name:
            attempt_root = Path(temp_name)
            clean_source = attempt_root / "payload"
            temporary_output = attempt_root / "candidate.dmg"
            shutil.copytree(source_root, clean_source, symlinks=True)
            _sync_filesystem()
            time.sleep(DMG_RETRY_DELAYS[attempt - 1] if attempt == 1 else 1)

            result = _run_captured(
                [
                    "hdiutil",
                    "create",
                    "-quiet",
                    "-volname",
                    volume_name,
                    "-srcfolder",
                    str(clean_source),
                    "-ov",
                    "-format",
                    "UDZO",
                    str(temporary_output),
                ],
                root,
            )
            if result.returncode == 0 and temporary_output.is_file():
                if _verify_dmg(temporary_output, root):
                    shutil.move(str(temporary_output), str(output))
                    print(f"DMG created and verified on attempt {attempt}: {output}", flush=True)
                    return
                failures.append(f"attempt {attempt}: hdiutil verify failed")
            else:
                detail = (result.stderr or result.stdout or "unknown hdiutil failure").strip()
                failures.append(f"attempt {attempt}: {detail[-500:]}")
                if not _retryable_hdiutil_failure(result):
                    raise RuntimeError(
                        "hdiutil create failed with a non-retryable error:\n" + detail
                    )

        if attempt < DMG_CREATE_ATTEMPTS:
            delay = DMG_RETRY_DELAYS[attempt - 1]
            print(
                f"[DMG][RETRY] transient DiskImages failure; retrying in {delay}s "
                f"({attempt}/{DMG_CREATE_ATTEMPTS})",
                flush=True,
            )
            _sync_filesystem()
            time.sleep(delay)

    raise RuntimeError(
        "Unable to create a verified DMG after transient hdiutil failures:\n- "
        + "\n- ".join(failures)
    )


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
    """Build an unsigned portable macOS app and place it in a verified DMG."""
    if sys.platform != "darwin":
        raise RuntimeError("The macOS builder must run on macOS.")

    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    if not skip_install:
        run([python, "-m", "pip", "install", "--upgrade", "pip"], root)
        run([python, "-m", "pip", "install", "-r", "requirements-build.txt"], root)
    run([python, "-m", "tools.prepare_vazirmatn"], root)

    if not skip_core:
        run([python, "-m", "tools.prepare_core"], root)
        run([python, "-m", "tools.prepare_optional_cores"], root)

    core = root / "core"
    assets = root / "assets"
    entrypoint = root / "app_v3.py"
    font_files = [assets / "fonts" / f"Vazirmatn-{weight}.ttf" for weight in ("Regular", "Medium", "Bold")]
    required = [entrypoint, assets / "app.png", core / "xray", core / "aether", core / "usque"]
    required.extend(font_files)
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
        "--collect-data",
        "certifi",
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
    bundle_name = f"{APP_NAME}-v{APP_VERSION}-macos-{architecture}"
    dmg_root = root / "build" / f"{bundle_name}-dmg"
    shutil.rmtree(dmg_root, ignore_errors=True)
    dmg_root.mkdir(parents=True)
    shutil.copytree(app, dmg_root / f"{APP_NAME}.app", symlinks=True)
    (dmg_root / "Applications").symlink_to("/Applications")
    _sync_filesystem()

    release = root / "release"
    release.mkdir(parents=True, exist_ok=True)
    output = release / f"{bundle_name}.dmg"
    _create_dmg_with_retry(
        source_root=dmg_root,
        output=output,
        volume_name=f"{APP_NAME} {APP_VERSION} {architecture}",
        root=root,
    )
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
