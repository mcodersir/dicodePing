from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime_assets"
ANDROID_AAR = ROOT / "dicodePing_android/local-maven/ir/dicode/local/libv2ray/26.7.11/libv2ray-26.7.11.aar"

XRAY_VERSION = "26.7.11"
SING_BOX_VERSION = "1.13.12"
ANDROID_CORE_VERSION = "26.7.11"
WINTUN_VERSION = "0.14.1"

XRAY_ASSETS = {
    "Xray-windows-64.zip": "af801b62c4d41d248d3db8016d4c6e2a7ccfb7ed443e3738aeb6f9e062321512",
    "Xray-linux-64.zip": "aa11c3685c71da0ffc71e511db50404609e7e963bb914b048f59a6a00af8930e",
    "Xray-macos-arm64-v8a.zip": "61f8f74d099098af710fa43613d9934d97b901dee909801d34f496cd463956d1",
    "Xray-macos-64.zip": "d8c116756d3a88a38a833a94bdf8bc801f69243ee888befcb56df8b4f1ec4878",
}
WINTUN_SHA256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"
ANDROID_AAR_SHA256 = "0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"
SING_BOX_ASSETS = {
    "sing-box-1.13.12-windows-amd64.zip": "e93fc531134eb1beb4efa3c74990a24e48456098a31c03b60d5ddf17f223cf98",
    "sing-box-1.13.12-linux-amd64.tar.gz": "1540533adb3df24f5ad5f14b5c7ca3dbc2401b10a1c1eb278fcadcada47ec6c4",
    "sing-box-1.13.12-darwin-arm64.tar.gz": "43eef86f0ea4a79c3696974f397a963c46a457ee46d1ffac9aa913944a5fc986",
    "sing-box-1.13.12-darwin-amd64.tar.gz": "f3275316451bf1983bc059599c69c8ed0232d53a619d15cfd535f95cc9a4477a",
}

USER_AGENT = "dicodePing-3.0-runtime"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, expected: str) -> bool:
    return path.is_file() and path.stat().st_size > 0 and sha256(path).lower() == expected.lower()


def _manual_source_dir() -> Path | None:
    raw = os.environ.get("DICODEPING_RUNTIME_SOURCE_DIR", "").strip().strip('"')
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def _copy_from_manual_source(target: Path, expected: str | None) -> bool:
    source_dir = _manual_source_dir()
    if source_dir is None:
        return False
    candidates = [
        source_dir / target.name,
        source_dir / "runtime_assets" / target.name,
        source_dir / "android" / target.name,
    ]
    for candidate in candidates:
        if not candidate.is_file() or candidate.stat().st_size == 0:
            continue
        if expected and not verify(candidate, expected):
            print(f"[skip] manual asset has wrong SHA-256: {candidate}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
        print(f"[ok] imported {target.name} from DICODEPING_RUNTIME_SOURCE_DIR")
        return True
    return False


def _download_urllib(url: str, partial: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def _curl_executable() -> str | None:
    return shutil.which("curl.exe") or shutil.which("curl")


def _run_curl(url: str, partial: Path, *, doh: str | None = None, bootstrap: str | None = None) -> None:
    curl = _curl_executable()
    if not curl:
        raise RuntimeError("curl is not installed")

    cmd = [
        curl,
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "4",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "20",
        "--max-time",
        "900",
        "--user-agent",
        USER_AGENT,
    ]
    # Windows' bundled curl commonly uses Schannel. On restricted networks its
    # certificate-revocation lookup can fail even when the HTTPS endpoint is
    # otherwise valid (CRYPT_E_REVOCATION_OFFLINE). Keep certificate validation
    # enabled but skip only the online revocation lookup for this fallback path.
    if os.name == "nt":
        cmd.append("--ssl-no-revoke")
    if doh and bootstrap:
        cmd.extend(["--doh-url", doh, "--resolve", bootstrap])
    cmd.extend(["--output", str(partial), url])

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"curl exited {proc.returncode}").strip()
        raise RuntimeError(detail)


def _dns_status(host: str) -> str:
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        if addresses:
            return ", ".join(addresses[:4])
        return "resolved with no addresses"
    except OSError as exc:
        return f"FAILED ({exc})"


def _finalize_download(partial: Path, target: Path, expected: str | None, url: str) -> None:
    if not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError(f"empty download: {url}")
    partial.replace(target)
    if expected and not verify(target, expected):
        actual = sha256(target)
        target.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {target.name}: {actual}")


def download(url: str, target: Path, expected: str | None = None) -> None:
    if expected and verify(target, expected):
        print(f"[ok] {target.relative_to(ROOT)}")
        return
    if not expected and target.is_file() and target.stat().st_size > 0:
        print(f"[ok] {target.relative_to(ROOT)}")
        return
    if _copy_from_manual_source(target, expected):
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    print(f"[get] {url}")

    attempts: list[tuple[str, callable]] = [("Python urllib", lambda: _download_urllib(url, partial))]
    if _curl_executable():
        attempts.extend(
            [
                ("curl/system DNS", lambda: _run_curl(url, partial)),
                (
                    "curl/Cloudflare DoH",
                    lambda: _run_curl(
                        url,
                        partial,
                        doh="https://cloudflare-dns.com/dns-query",
                        bootstrap="cloudflare-dns.com:443:1.1.1.1",
                    ),
                ),
                (
                    "curl/Google DoH",
                    lambda: _run_curl(
                        url,
                        partial,
                        doh="https://dns.google/dns-query",
                        bootstrap="dns.google:443:8.8.8.8",
                    ),
                ),
            ]
        )

    errors: list[str] = []
    for label, action in attempts:
        partial.unlink(missing_ok=True)
        try:
            print(f"  -> {label}")
            action()
            _finalize_download(partial, target, expected, url)
            print(f"[ok] {target.relative_to(ROOT)}")
            return
        except Exception as exc:  # each transport is intentionally isolated
            errors.append(f"{label}: {exc}")
            partial.unlink(missing_ok=True)

    host = urllib.parse.urlparse(url).hostname or "github.com"
    dns = _dns_status(host)
    details = "\n    ".join(errors[-4:])
    raise RuntimeError(
        f"all download methods failed for {target.name}\n"
        f"  DNS {host}: {dns}\n"
        f"  attempts:\n    {details}\n"
        "  If GitHub is blocked on this network, download the pinned assets with a browser/VPN on another machine,\n"
        "  put them in one folder, then run:\n"
        "    set DICODEPING_RUNTIME_SOURCE_DIR=C:\\path\\to\\runtime-files\n"
        "    PREPARE_V3_RUNTIME.bat"
    )


def fetch_desktop() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    for name, digest in XRAY_ASSETS.items():
        download(f"https://github.com/XTLS/Xray-core/releases/download/v{XRAY_VERSION}/{name}", RUNTIME / name, digest)
    download(f"https://www.wintun.net/builds/wintun-{WINTUN_VERSION}.zip", RUNTIME / f"wintun-{WINTUN_VERSION}.zip", WINTUN_SHA256)

    # sing-box v1.13.12 does not publish a standalone *-checksums.txt asset.
    # GitHub exposes SHA-256 digests per release asset; those immutable digests
    # are pinned above and in RUNTIME_ASSETS.lock.json.
    base = f"https://github.com/SagerNet/sing-box/releases/download/v{SING_BOX_VERSION}"
    for name, expected in SING_BOX_ASSETS.items():
        download(f"{base}/{name}", RUNTIME / name, expected)


def fetch_android() -> None:
    download(
        f"https://github.com/2dust/AndroidLibXrayLite/releases/download/v{ANDROID_CORE_VERSION}/libv2ray.aar",
        ANDROID_AAR,
        ANDROID_AAR_SHA256,
    )


def verify_all(desktop: bool, android: bool) -> None:
    missing: list[str] = []
    if desktop:
        for name, digest in XRAY_ASSETS.items():
            if not verify(RUNTIME / name, digest):
                missing.append(name)
        if not verify(RUNTIME / f"wintun-{WINTUN_VERSION}.zip", WINTUN_SHA256):
            missing.append(f"wintun-{WINTUN_VERSION}.zip")
        for name, expected in SING_BOX_ASSETS.items():
            if not verify(RUNTIME / name, expected):
                missing.append(name)
    if android and not verify(ANDROID_AAR, ANDROID_AAR_SHA256):
        missing.append(str(ANDROID_AAR.relative_to(ROOT)))
    if missing:
        raise RuntimeError("runtime set is incomplete or invalid:\n- " + "\n- ".join(missing))
    print("Pinned runtime set verified")


def print_network_diagnostics() -> None:
    print("Network diagnostics:")
    for host in ("github.com", "release-assets.githubusercontent.com", "www.wintun.net"):
        print(f"  {host}: {_dns_status(host)}")
    curl = _curl_executable()
    print(f"  curl: {curl or 'not found'}")
    manual = _manual_source_dir()
    print(f"  manual source: {manual if manual else 'not configured'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and verify pinned Version 3 runtime assets.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--desktop", action="store_true", help="Fetch desktop runtimes only")
    group.add_argument("--android", action="store_true", help="Fetch Android runtime only")
    parser.add_argument("--verify-only", action="store_true", help="Do not download; verify files already present")
    parser.add_argument("--diagnose", action="store_true", help="Print DNS/download diagnostics and exit")
    args = parser.parse_args()

    if args.diagnose:
        print_network_diagnostics()
        return 0

    desktop = not args.android
    android = not args.desktop
    try:
        if not args.verify_only:
            if desktop:
                fetch_desktop()
            if android:
                fetch_android()
        verify_all(desktop, android)
        return 0
    except KeyboardInterrupt:
        print("Runtime preparation cancelled.")
        return 130
    except Exception as exc:
        print(f"Runtime preparation failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
