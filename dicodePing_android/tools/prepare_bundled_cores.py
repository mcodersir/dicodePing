#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

AETHER_VERSION = "1.4.0"
USQUE_VERSION = "4.2.1"


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "dicodePing-build/1.9.0-rc.9"})
    with urllib.request.urlopen(request, timeout=90) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_upstream_sha(asset: Path, checksum_file: Path) -> None:
    expected = checksum_file.read_text(encoding="utf-8", errors="ignore").strip().split()[0].lower()
    actual = sha256(asset)
    if len(expected) != 64 or actual != expected:
        raise RuntimeError(f"SHA-256 mismatch for {asset.name}: expected {expected}, got {actual}")


def prepare_aether(work: Path, jni: Path) -> None:
    assets = {
        "arm64-v8a": "aether-android-arm64.tar.gz",
        "x86_64": "aether-android-x86_64.tar.gz",
    }
    for abi, name in assets.items():
        base = f"https://github.com/CluvexStudio/Aether/releases/download/v{AETHER_VERSION}/{name}"
        archive = work / name
        checksum = work / f"{name}.sha256"
        download(base, archive)
        download(base + ".sha256", checksum)
        verify_upstream_sha(archive, checksum)
        extract = work / f"aether-{abi}"
        extract.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as bundle:
            members = [m for m in bundle.getmembers() if Path(m.name).name == "aether" and m.isfile()]
            if len(members) != 1:
                raise RuntimeError(f"Aether executable missing in {name}")
            source = bundle.extractfile(members[0])
            if source is None:
                raise RuntimeError(f"Cannot extract Aether from {name}")
            target = jni / abi / "libaether.so"
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(">", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def prepare_usque(work: Path, jni: Path) -> None:
    source = work / "usque"
    run([
        "git", "clone", "--depth", "1", "--branch", f"v{USQUE_VERSION}",
        "https://github.com/Diniboy1123/usque.git", str(source),
    ], work)
    for abi, goarch in (("arm64-v8a", "arm64"), ("x86_64", "amd64")):
        target = jni / abi / "libusque.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({"GOOS": "android", "GOARCH": goarch, "CGO_ENABLED": "0"})
        run([
            "go", "build", "-trimpath", "-buildmode=pie", "-ldflags=-s -w",
            "-o", str(target), ".",
        ], source, env)
        target.chmod(0o755)
        if target.stat().st_size < 500_000:
            raise RuntimeError(f"Usque Android build is unexpectedly small: {target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project = args.project.resolve()
    jni = project / "app" / "src" / "main" / "jniLibs"
    shutil.rmtree(jni, ignore_errors=True)
    with tempfile.TemporaryDirectory(prefix="dicodeping-android-cores-") as temp:
        work = Path(temp)
        prepare_aether(work, jni)
        prepare_usque(work, jni)
    for abi in ("arm64-v8a", "x86_64"):
        for name in ("libaether.so", "libusque.so"):
            path = jni / abi / name
            if not path.is_file():
                raise RuntimeError(f"Missing bundled helper: {path}")
            if path.stat().st_size < 500_000:
                raise RuntimeError(f"Bundled helper is unexpectedly small: {path}")
            if path.read_bytes()[:4] != b"\x7fELF":
                raise RuntimeError(f"Bundled helper is not an Android ELF executable: {path}")
            print(f"Prepared {path.relative_to(project)} sha256={sha256(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
