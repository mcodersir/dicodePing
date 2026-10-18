#!/usr/bin/env python3
"""Archive the published client with Unix executable permissions intact."""
import argparse
import hashlib
import pathlib
import stat
import zipfile


def package(root: pathlib.Path, archive: pathlib.Path, windows: bool, cli: bool = False) -> None:
    executables = [] if windows else [
        "dicodeping" if cli else "DicodePing", "bin/xray/xray", "bin/mihomo/mihomo", "bin/sing_box/sing-box",
        "bin/fox/dicode-fox", "bin/aether/aether", "bin/aether/pt/lyrebird", "bin/aether/pt/psiphon-tunnel-core",
    ]
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
    archive = args.output / ("DicodePing-4.9.4-" + args.platform + ("-cli.zip" if args.edition == "cli" else "-portable.zip"))
    package(args.root, archive, args.platform == "windows-x64", args.edition == "cli")
    hasher = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    (args.output / ("SHA256SUMS-" + args.platform + ("-cli" if args.edition == "cli" else "") + ".txt")).write_text(
        digest + "  " + archive.name + "\n", encoding="utf-8"
    )
    print("Archived and verified", archive.name)
