from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ASSETS = ROOT / "runtime_assets"
XRAY_VERSION = "26.7.11"
SING_BOX_VERSION = "1.13.12"
XRAY_SHA256 = {
    "Xray-windows-64.zip": "af801b62c4d41d248d3db8016d4c6e2a7ccfb7ed443e3738aeb6f9e062321512",
    "Xray-linux-64.zip": "aa11c3685c71da0ffc71e511db50404609e7e963bb914b048f59a6a00af8930e",
    "Xray-macos-arm64-v8a.zip": "61f8f74d099098af710fa43613d9934d97b901dee909801d34f496cd463956d1",
    "Xray-macos-64.zip": "d8c116756d3a88a38a833a94bdf8bc801f69243ee888befcb56df8b4f1ec4878",
}
WINTUN_VERSION = "0.14.1"
WINTUN_SHA256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"
SING_BOX_SHA256 = {
    "sing-box-1.13.12-windows-amd64.zip": "e93fc531134eb1beb4efa3c74990a24e48456098a31c03b60d5ddf17f223cf98",
    "sing-box-1.13.12-linux-amd64.tar.gz": "1540533adb3df24f5ad5f14b5c7ca3dbc2401b10a1c1eb278fcadcada47ec6c4",
    "sing-box-1.13.12-darwin-arm64.tar.gz": "43eef86f0ea4a79c3696974f397a963c46a457ee46d1ffac9aa913944a5fc986",
    "sing-box-1.13.12-darwin-amd64.tar.gz": "f3275316451bf1983bc059599c69c8ed0232d53a619d15cfd535f95cc9a4477a",
}


def run(command: list[str]) -> None:
    print(">", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "dicodePing-v3-build"})
    with urllib.request.urlopen(req, timeout=90) as response:
        data = response.read()
    if not data:
        raise RuntimeError(f"empty download: {url}")
    return data


def _asset_bytes(name: str, url: str) -> bytes:
    local = RUNTIME_ASSETS / name
    if local.is_file():
        data = local.read_bytes()
        if data:
            return data
    return _download(url)


def _verify(data: bytes, expected: str, name: str) -> None:
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected.lower():
        raise RuntimeError(f"SHA-256 mismatch for {name}: {actual}")


def _platform() -> tuple[str, str, str]:
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if os.name == "nt":
        return "win-x64", "windows", "amd64"
    if sys.platform == "darwin":
        return ("osx-arm64", "darwin", "arm64") if arm else ("osx-x64", "darwin", "amd64")
    if sys.platform.startswith("linux"):
        return ("linux-arm64", "linux", "arm64") if arm else ("linux-x64", "linux", "amd64")
    raise RuntimeError(f"unsupported build platform: {sys.platform}/{machine}")


def _xray_asset() -> str:
    machine = platform.machine().lower()
    if os.name == "nt":
        return "Xray-windows-64.zip"
    if sys.platform == "darwin":
        return "Xray-macos-arm64-v8a.zip" if machine in {"arm64", "aarch64"} else "Xray-macos-64.zip"
    if sys.platform.startswith("linux"):
        if machine in {"arm64", "aarch64"}:
            return "Xray-linux-arm64-v8a.zip"
        return "Xray-linux-64.zip"
    raise RuntimeError("unsupported platform")


def _prepare_xray(engine: Path) -> None:
    asset = _xray_asset()
    data = _asset_bytes(asset, f"https://github.com/XTLS/Xray-core/releases/download/v{XRAY_VERSION}/{asset}")
    expected = XRAY_SHA256.get(asset)
    if expected:
        _verify(data, expected, asset)
    target = engine / "bin" / "xray"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        exe = "xray.exe" if os.name == "nt" else "xray"
        if exe not in names:
            raise RuntimeError(f"{asset} does not contain {exe}")
        for name in (exe, "geoip.dat", "geosite.dat"):
            if name in names:
                (target / name).write_bytes(archive.read(name))
    if os.name != "nt":
        (target / "xray").chmod(0o755)


def _prepare_wintun(engine: Path) -> None:
    if os.name != "nt":
        return
    data = _asset_bytes(f"wintun-{WINTUN_VERSION}.zip", f"https://www.wintun.net/builds/wintun-{WINTUN_VERSION}.zip")
    _verify(data, WINTUN_SHA256, "wintun")
    target = engine / "bin" / "xray"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        candidates = [n for n in archive.namelist() if n.lower().endswith("/bin/amd64/wintun.dll")]
        if not candidates:
            candidates = [n for n in archive.namelist() if n.lower().endswith("wintun.dll") and "amd64" in n.lower()]
        if not candidates:
            raise RuntimeError("wintun.dll (amd64) not found")
        (target / "wintun.dll").write_bytes(archive.read(candidates[0]))


def _prepare_sing_box(engine: Path, os_name: str, arch: str) -> None:
    ext = "zip" if os_name == "windows" else "tar.gz"
    stem = f"sing-box-{SING_BOX_VERSION}-{os_name}-{arch}"
    asset = f"{stem}.{ext}"
    base = f"https://github.com/SagerNet/sing-box/releases/download/v{SING_BOX_VERSION}"
    expected = SING_BOX_SHA256.get(asset)
    if not expected:
        raise RuntimeError(f"unsupported pinned sing-box asset: {asset}")
    data = _asset_bytes(asset, f"{base}/{asset}")
    _verify(data, expected, asset)
    target = engine / "bin" / "sing_box"
    target.mkdir(parents=True, exist_ok=True)
    exe = "sing-box.exe" if os.name == "nt" else "sing-box"
    if ext == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            candidates = [n for n in archive.namelist() if n.endswith("/" + exe) or n == exe]
            if not candidates:
                raise RuntimeError(f"{asset} does not contain {exe}")
            (target / exe).write_bytes(archive.read(candidates[0]))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            member = next((m for m in archive.getmembers() if m.name.endswith("/" + exe) or m.name == exe), None)
            if not member:
                raise RuntimeError(f"{asset} does not contain {exe}")
            stream = archive.extractfile(member)
            if not stream:
                raise RuntimeError(f"could not extract {exe}")
            (target / exe).write_bytes(stream.read())
    if os.name != "nt":
        (target / exe).chmod(0o755)


def prepare(*, skip_download: bool = False) -> Path:
    rid, os_name, arch = _platform()
    engine = ROOT / "build" / "engine" / rid
    shutil.rmtree(engine, ignore_errors=True)
    engine.mkdir(parents=True, exist_ok=True)
    run([
        "dotnet", "publish", str(ROOT / "corehost" / "dicodePing.CoreHost.csproj"),
        "-c", "Release", "-r", rid, "--self-contained", "true",
        "-p:PublishSingleFile=true", "-p:IncludeNativeLibrariesForSelfExtract=true",
        "-p:DebugType=None", "-p:DebugSymbols=false", "-o", str(engine),
    ])
    host = engine / ("dicodePing.CoreHost.exe" if os.name == "nt" else "dicodePing.CoreHost")
    if not host.exists():
        raise RuntimeError(f"CoreHost publish did not produce {host.name}")
    if not skip_download:
        _prepare_xray(engine)
        _prepare_wintun(engine)
        _prepare_sing_box(engine, os_name, arch)
    required = [host, engine / "bin" / "xray" / ("xray.exe" if os.name == "nt" else "xray"), engine / "bin" / "sing_box" / ("sing-box.exe" if os.name == "nt" else "sing-box")]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise RuntimeError("engine is incomplete:\n- " + "\n- ".join(missing))
    return engine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    try:
        print(prepare(skip_download=args.skip_download))
        return 0
    except Exception as exc:
        print(f"Engine preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
