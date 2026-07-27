#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

AETHER_VERSION = "1.4.0"
USQUE_VERSION = "4.2.1"
ANDROID_API = 24


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "dicodePing-build/1.9.0-rc.10-hotfix3"})
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
        with tarfile.open(archive, "r:gz") as bundle:
            members = [member for member in bundle.getmembers() if Path(member.name).name == "aether" and member.isfile()]
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


def _host_prebuilt_tag() -> str:
    if sys.platform.startswith("linux"):
        return "linux-x86_64"
    if sys.platform == "darwin":
        return "darwin-x86_64"
    if os.name == "nt":
        return "windows-x86_64"
    raise RuntimeError(f"Unsupported build host for Android NDK: {sys.platform}")


def find_ndk() -> Path:
    explicit = [os.environ.get("ANDROID_NDK_HOME"), os.environ.get("ANDROID_NDK_ROOT")]
    for raw in explicit:
        if raw:
            candidate = Path(raw).expanduser().resolve()
            if candidate.is_dir():
                return candidate

    sdk_raw = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if sdk_raw:
        ndk_root = Path(sdk_raw).expanduser().resolve() / "ndk"
        if ndk_root.is_dir():
            versions = sorted(
                (path for path in ndk_root.iterdir() if path.is_dir()),
                key=lambda path: tuple(int(part) if part.isdigit() else part for part in path.name.replace("-", ".").split(".")),
                reverse=True,
            )
            if versions:
                return versions[0]
    raise RuntimeError(
        "Android NDK was not found. Set ANDROID_NDK_HOME/ANDROID_NDK_ROOT or install an NDK under ANDROID_HOME/ndk."
    )


def ndk_toolchain(ndk: Path) -> Path:
    toolchain = ndk / "toolchains" / "llvm" / "prebuilt" / _host_prebuilt_tag() / "bin"
    if not toolchain.is_dir():
        raise RuntimeError(f"Android NDK LLVM toolchain was not found: {toolchain}")
    return toolchain


def prepare_usque(work: Path, jni: Path) -> None:
    source = work / "usque"
    run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "clone",
            "--depth",
            "1",
            "--branch",
            f"v{USQUE_VERSION}",
            "https://github.com/Diniboy1123/usque.git",
            str(source),
        ],
        work,
    )

    toolchain = ndk_toolchain(find_ndk())
    llvm_ar = toolchain / ("llvm-ar.exe" if os.name == "nt" else "llvm-ar")
    builds = (
        ("arm64-v8a", "arm64", "aarch64-linux-android"),
        ("x86_64", "amd64", "x86_64-linux-android"),
    )
    for abi, goarch, clang_prefix in builds:
        suffix = ".cmd" if os.name == "nt" else ""
        cc = toolchain / f"{clang_prefix}{ANDROID_API}-clang{suffix}"
        cxx = toolchain / f"{clang_prefix}{ANDROID_API}-clang++{suffix}"
        if not cc.is_file() or not cxx.is_file() or not llvm_ar.is_file():
            raise RuntimeError(f"Required NDK cross tools are missing for {abi}: {cc}, {cxx}, {llvm_ar}")

        target = jni / abi / "libusque.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "GOOS": "android",
                "GOARCH": goarch,
                "CGO_ENABLED": "1",
                "CC": str(cc),
                "CXX": str(cxx),
                "AR": str(llvm_ar),
                "GOTOOLCHAIN": "auto",
            }
        )
        if goarch == "amd64":
            # Android x86_64 implements the x86-64-v2 baseline.
            env["GOAMD64"] = "v2"
        run(
            [
                "go",
                "build",
                "-trimpath",
                "-buildmode=pie",
                "-ldflags=-s -w -extldflags=-Wl,-z,max-page-size=16384",
                "-o",
                str(target),
                ".",
            ],
            source,
            env,
        )
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
