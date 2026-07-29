#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

AETHER_MOBILE_COMMIT = "5c5a22e6b4c8fbfc2416966bb83a16b812ef7988"
AETHER_VERSION = f"QW-AI-Code/Aether@{AETHER_MOBILE_COMMIT[:12]}"
USQUE_VERSION = "4.2.1"
ANDROID_API = 24


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "dicodePing-build/2.0.0"})
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
    """Build Aether from QW-AI-Code/Aether's audited mobile source snapshot.

    The mobile project vendors the compatible Aether/quiche source. We reuse
    that source and its fetch step, but build only dicodePing's supported
    64-bit ABIs. The result stays a separate executable process exposed as
    libaether.so; no foreign Android UI code is copied into this application.
    """
    source = work / "aether-mobile"
    run(["git", "clone", "--no-checkout", "--filter=blob:none", "https://github.com/QW-AI-Code/Aether.git", str(source)], work)
    run(["git", "fetch", "--depth", "1", "origin", AETHER_MOBILE_COMMIT], source)
    run(["git", "checkout", "--detach", AETHER_MOBILE_COMMIT], source)

    env = os.environ.copy()
    env["ANDROID_API"] = str(ANDROID_API)
    env["AETHER_REPO"] = "QW-AI-Code/Aether"

    # QW-AI-Code/Aether vendors the exact engine snapshot used by its Android
    # client. Prefer it directly: this avoids cloning the unrelated TUN helper
    # and makes the dicodePing build faster and more reproducible. Keep the
    # upstream fetch script as a compatibility fallback if the layout changes.
    native = source / "native" / "aether"
    if not any(native.rglob("Cargo.toml")):
        fetch = source / "scripts" / "fetch-natives.sh"
        if not fetch.is_file():
            raise RuntimeError("QW-AI-Code/Aether mobile native source is missing")
        env.pop("AETHER_FORCE_CLONE", None)
        run(["bash", str(fetch)], source, env)
        native = source / ".native" / "aether"
    manifests = sorted(native.rglob("Cargo.toml"))
    crate = next(
        (manifest.parent for manifest in manifests if (manifest.parent / "src" / "main.rs").is_file() and "quiche" not in manifest.parts),
        None,
    )
    if crate is None:
        raise RuntimeError("Aether mobile vendored binary crate was not found")
    cargo_target = native / "target"
    build_env = env.copy()
    build_env["ANDROID_NDK_ROOT"] = str(find_ndk())
    build_env["ANDROID_NDK_HOME"] = str(find_ndk())
    build_env["CARGO_TARGET_DIR"] = str(cargo_target)

    bin_name = "aether"
    cargo_toml = (crate / "Cargo.toml").read_text(encoding="utf-8", errors="ignore")
    match = __import__("re").search(r'^name\s*=\s*"([^"]+)"', cargo_toml, __import__("re").MULTILINE)
    if match:
        bin_name = match.group(1)

    builds = (
        ("arm64-v8a", "aarch64-linux-android"),
        ("x86_64", "x86_64-linux-android"),
    )
    for abi, triple in builds:
        run(
            ["cargo", "ndk", "-t", abi, "--platform", str(ANDROID_API), "build", "--release"],
            crate,
            build_env,
        )
        release_dir = cargo_target / triple / "release"
        candidate = release_dir / bin_name
        if not candidate.is_file():
            candidate = next(
                (path for path in release_dir.iterdir() if path.is_file() and path.suffix not in {".d", ".rlib", ".rmeta", ".so"}),
                None,
            )
        if candidate is None or not candidate.is_file():
            raise RuntimeError(f"Aether mobile build did not produce an executable for {abi}")
        target = jni / abi / "libaether.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
        target.chmod(0o755)
        if target.stat().st_size < 500_000:
            raise RuntimeError(f"Aether Android build is unexpectedly small: {target}")


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
    manifest_entries = []
    for abi in ("arm64-v8a", "x86_64"):
        expected_machine = 183 if abi == "arm64-v8a" else 62
        for name in ("libaether.so", "libusque.so"):
            path = jni / abi / name
            if not path.is_file():
                raise RuntimeError(f"Missing bundled helper: {path}")
            if path.stat().st_size < 500_000:
                raise RuntimeError(f"Bundled helper is unexpectedly small: {path}")
            with path.open("rb") as stream:
                header = stream.read(20)
            if header[:4] != b"\x7fELF":
                raise RuntimeError(f"Bundled helper is not an Android ELF executable: {path}")
            machine = int.from_bytes(header[18:20], "little")
            if machine != expected_machine:
                raise RuntimeError(
                    f"Bundled helper ABI mismatch for {path}: expected ELF machine {expected_machine}, got {machine}"
                )
            digest = sha256(path)
            manifest_entries.append(
                {
                    "abi": abi,
                    "file": name,
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                    "elfMachine": machine,
                }
            )
            print(f"Prepared {path.relative_to(project)} sha256={digest}")

    assets_dir = project / "app" / "src" / "main" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = assets_dir / "bundled_cores.json"
    manifest_path.write_text(
        json.dumps(
            {
                "release": "2.0.0",
                "aether": AETHER_VERSION,
                "usque": USQUE_VERSION,
                "abis": ["arm64-v8a", "x86_64"],
                "entries": manifest_entries,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {manifest_path.relative_to(project)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
