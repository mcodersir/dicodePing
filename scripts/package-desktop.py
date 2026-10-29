#!/usr/bin/env python3
"""Archive the published client with Unix executable permissions intact."""
import argparse
import hashlib
import pathlib
import stat
import zipfile
import shutil
import plistlib
import subprocess
import tempfile


def desktop_bundle(root: pathlib.Path, platform: str, output: pathlib.Path) -> pathlib.Path:
    """Build a Finder application, or a Linux desktop/install entry point."""
    icon = pathlib.Path('apps/desktop/v2rayN.Desktop/DicodePing.png')
    if platform.startswith('macos'):
        stage = output / 'app-bundle'
        app = stage / 'DicodePing.app'
        if app.exists(): shutil.rmtree(app)
        binary = app / 'Contents/MacOS'
        shutil.copytree(root, binary)
        resources = app / 'Contents/Resources'
        resources.mkdir(parents=True)
        shutil.copy2(icon, resources / 'DicodePing.png')
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleName': 'DicodePing', 'CFBundleDisplayName': 'DicodePing',
            'CFBundleIdentifier': 'ir.dicode.ping.desktop', 'CFBundlePackageType': 'APPL',
            'CFBundleExecutable': 'DicodePing', 'CFBundleShortVersionString': '4.9.91',
            'CFBundleVersion': '409910', 'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '12.0',
        }))
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        (stage / 'README.txt').write_text('Move DicodePing.app to Applications and open it. The graphical interface runs as your user; TUN asks for administrator authorization inside the application. This community build is ad-hoc signed, not Apple notarized.\n')
        return stage
    if platform == 'linux-x64':
        shutil.copy2(icon, root / 'DicodePing.png')
        (root / 'Start-DicodePing.sh').write_text('#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec ./DicodePing "$@"\n')
        (root / 'Start-DicodePing.sh').chmod(0o755)
        entry = '[Desktop Entry]\nType=Application\nName=DicodePing\nComment=VPN client\nExec=/opt/dicodeping/DicodePing\nIcon=/opt/dicodeping/DicodePing.png\nTerminal=false\nCategories=Network;\nStartupWMClass=DicodePing\n'
        (root / 'DicodePing.desktop').write_text(entry)
        (root / 'Install-Desktop-Entry.sh').write_text('''#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
app_dir=$(pwd)
dest="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$dest"
sed "s|/opt/dicodeping|$app_dir|g" DicodePing.desktop > "$dest/DicodePing.desktop"
chmod +x "$dest/DicodePing.desktop"
''')
        (root / 'Install-Desktop-Entry.sh').chmod(0o755)
        with tempfile.TemporaryDirectory(prefix='dicode-deb-') as tmp:
            stage = pathlib.Path(tmp)
            shutil.copytree(root, stage / 'opt/dicodeping')
            control = stage / 'DEBIAN'; control.mkdir()
            (control / 'control').write_text('Package: dicodeping\nVersion: 4.9.91\nArchitecture: amd64\nMaintainer: DicodePing\nDepends: libx11-6, libice6, libsm6, libfontconfig1, libglib2.0-0, sudo\nDescription: DicodePing graphical VPN client\n')
            entries = stage / 'usr/share/applications'; entries.mkdir(parents=True)
            (entries / 'dicodeping.desktop').write_text(entry)
            subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(stage), str(output / 'DicodePing-4.9.91-linux-x64.deb')], check=True)
    return root


def package(root: pathlib.Path, archive: pathlib.Path, windows: bool, cli: bool = False) -> None:
    prefix = 'DicodePing.app/Contents/MacOS/' if (root / 'DicodePing.app').exists() else ''
    executables = [] if windows else [prefix + name for name in [
        "dicodeping" if cli else "DicodePing", "bin/xray/xray", "bin/mihomo/mihomo",
        "bin/fox/dicode-fox", "bin/aether/aether", "bin/aether/pt/lyrebird", "bin/aether/pt/psiphon-tunnel-core",
    ]]
    for name in executables:
        if not (root / name).is_file() or not (root / name).stat().st_mode & 0o111:
            raise RuntimeError("Published executable is missing or not executable: " + name)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(root.rglob("*")):
            if file.is_file():
                bundle.write(file, file.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        for name in executables:
            entry = bundle.getinfo(name)
            mode = entry.external_attr >> 16
            if entry.create_system != 3 or not stat.S_ISREG(mode) or not mode & 0o111:
                raise RuntimeError("Archive lost Unix executable permissions: " + name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="publish", type=pathlib.Path)
    parser.add_argument("--platform", required=True, choices=["windows-x64", "linux-x64", "macos-x64", "macos-arm64"])
    parser.add_argument("--output", default="dist", type=pathlib.Path)
    parser.add_argument("--edition", choices=["desktop", "cli"], default="desktop")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.edition == 'desktop' and args.platform != 'windows-x64':
        args.root = desktop_bundle(args.root, args.platform, args.output)
    archive = args.output / ("DicodePing-4.9.91-" + args.platform + ("-cli.zip" if args.edition == "cli" else "-portable.zip"))
    package(args.root, archive, args.platform == "windows-x64", args.edition == "cli")
    hasher = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    (args.output / ("SHA256SUMS-" + args.platform + ("-cli" if args.edition == "cli" else "") + ".txt")).write_text(
        digest + "  " + archive.name + "\n", encoding="utf-8"
    )
    if args.platform == 'linux-x64' and args.edition == 'desktop':
        deb = args.output / 'DicodePing-4.9.91-linux-x64.deb'
        with (args.output / 'SHA256SUMS-linux-x64.txt').open('a') as sums:
            sums.write(hashlib.sha256(deb.read_bytes()).hexdigest() + '  ' + deb.name + '\n')
    print("Archived and verified", archive.name)
