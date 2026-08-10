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

from tools.build_desktop_common import APP_NAME, APP_VERSION, ROOT, prepare_build, pyinstaller_base, run

BUNDLE_ID = "ir.dicode.dicodePing"


def _captured(command: list[str]) -> subprocess.CompletedProcess[str]:
    print(">", subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _build_icon() -> Path:
    icon_root = ROOT / "build" / "macos-icon"
    iconset = icon_root / f"{APP_NAME}.iconset"
    icon = icon_root / f"{APP_NAME}.icns"
    shutil.rmtree(icon_root, ignore_errors=True)
    iconset.mkdir(parents=True)
    for size in (16, 32, 128, 256, 512):
        run(["sips", "-z", str(size), str(size), str(ROOT / "assets" / "app.png"), "--out", str(iconset / f"icon_{size}x{size}.png")])
        run(["sips", "-z", str(size * 2), str(size * 2), str(ROOT / "assets" / "app.png"), "--out", str(iconset / f"icon_{size}x{size}@2x.png")])
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(icon)])
    return icon


def _create_dmg(payload: Path, output: Path, volume_name: str) -> None:
    output.unlink(missing_ok=True)
    errors: list[str] = []
    for attempt in range(1, 6):
        with tempfile.TemporaryDirectory(prefix="dicodeping-dmg-", dir=ROOT / "build") as tmp:
            candidate = Path(tmp) / "candidate.dmg"
            result = _captured([
                "hdiutil", "create", "-quiet", "-volname", volume_name,
                "-srcfolder", str(payload), "-ov", "-format", "UDZO", str(candidate),
            ])
            if result.returncode == 0 and candidate.is_file():
                verify = _captured(["hdiutil", "verify", str(candidate)])
                if verify.returncode == 0:
                    shutil.move(str(candidate), output)
                    return
                errors.append(verify.stderr or verify.stdout or "verify failed")
            else:
                errors.append(result.stderr or result.stdout or "create failed")
        time.sleep(min(2 * attempt, 8))
    raise RuntimeError("DMG creation failed: " + " | ".join(x.strip()[-300:] for x in errors))


def build(skip_install: bool = False) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("macOS builder must run on macOS")
    engine = prepare_build(skip_install)
    icon = _build_icon()
    spec = ROOT / "build" / "macos-spec"
    spec.mkdir(parents=True, exist_ok=True)
    cmd = pyinstaller_base(engine)
    cmd += [
        "--icon", str(icon),
        "--osx-bundle-identifier", BUNDLE_ID,
        "--specpath", str(spec),
        str(ROOT / "app.py"),
    ]
    run(cmd)
    app = ROOT / "dist" / f"{APP_NAME}.app"
    if not app.is_dir():
        raise FileNotFoundError(app)

    entitlements = ROOT / "packaging" / "macos" / "entitlements.plist"
    if entitlements.is_file():
        run(["codesign", "--force", "--deep", "--sign", "-", "--entitlements", str(entitlements), str(app)])
        run(["codesign", "--verify", "--deep", "--strict", str(app)])

    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
    bundle_name = f"{APP_NAME}-v{APP_VERSION}-macos-{arch}"
    payload = ROOT / "build" / f"{bundle_name}-dmg"
    shutil.rmtree(payload, ignore_errors=True)
    payload.mkdir(parents=True)
    shutil.copytree(app, payload / f"{APP_NAME}.app", symlinks=True)
    (payload / "Applications").symlink_to("/Applications")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, payload / name)

    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    out = release / f"{bundle_name}.dmg"
    _create_dmg(payload, out, f"{APP_NAME} {APP_VERSION}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()
    try:
        print(build(args.skip_install))
        return 0
    except Exception as exc:
        print(f"macOS build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
