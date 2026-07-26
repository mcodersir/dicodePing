"""Verified connection-core discovery and installation.

Unsigned Windows/Linux packages keep third-party tunnel executables outside
the GUI bundle. A core installed at runtime requires explicit user action, an
allow-listed HTTPS download, strict archive extraction, and pinned SHA-256
verification. Trusted Windows/macOS releases may instead carry visible helpers
that are signed as part of the platform release.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .constants import BUNDLED_CORE_DIR, DATA_DIR
from .diagnostics import get_logger
from .core_runtime import CancellationToken, CoreState

LOGGER = get_logger("core_manager")
CORES_DIR = DATA_DIR / "cores"
ACTIVE_CORE_FILE = DATA_DIR / "active_core.json"
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 128
MAX_EXPANDED_BYTES = 350 * 1024 * 1024
MAX_COMPRESSION_RATIO = 120
MAX_REDIRECTS = 4
CONNECT_TIMEOUT_SECONDS = 15.0
READ_TIMEOUT_SECONDS = 30.0
OVERALL_TIMEOUT_SECONDS = 180.0
MIN_FREE_SPACE_BYTES = 700 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "raw.githubusercontent.com",
    }
)


@dataclass(frozen=True, slots=True)
class CoreDescriptor:
    id: str
    name: str
    description: str
    download_url: str
    sha256: str
    archive_kind: str
    executable_name: str
    size_hint_mb: int
    upstream: str
    version: str


_windows = os.name == "nt"
_macos = sys.platform == "darwin"
_machine = platform.machine().lower()
_arm64 = _machine in {"arm64", "aarch64"}


def _platform_asset(
    *,
    windows: tuple[str, str],
    linux: tuple[str, str],
    macos_x64: tuple[str, str],
    macos_arm64: tuple[str, str],
) -> tuple[str, str]:
    if _windows:
        return windows
    if _macos:
        return macos_arm64 if _arm64 else macos_x64
    return linux


_aether_asset, _aether_sha = _platform_asset(
    windows=("aether-windows-x86_64.zip", "4b4ac4c2dcade01c13bc6f1706f7f62e94c3b3058184212692bd9d598c0ce9b4"),
    linux=("aether-linux-x86_64.tar.gz", "683dc190a948e8555fc9738ef2d1be403d95606e191e75f0e6941012c6b869cd"),
    macos_x64=("aether-macos-x86_64.tar.gz", "ae2cd0a987d709ae017a9ea762b26f9276c418beb2a6f882253563c44b5aec1f"),
    macos_arm64=("aether-macos-arm64.tar.gz", "a966c0d72aa90a6db000172f9bf88f225377fe4d8546cf2340ef6aee1ccbd958"),
)
_usque_asset, _usque_sha = _platform_asset(
    windows=("usque_4.2.1_windows_amd64.zip", "f6f7f0a1a2bc9bcc15cf563ec1f892d00690a92c086b23ed3211b802209099e7"),
    linux=("usque_4.2.1_linux_amd64.zip", "4117e20695078af9c11edecd1a826c009bbc7ea0b7f64458612b4198910bc313"),
    macos_x64=("usque_4.2.1_darwin_amd64.zip", "1eb41e34bf4cd0b81e06222ef844cea75eb56229a62fe29c07cf8e7bd253357d"),
    macos_arm64=("usque_4.2.1_darwin_arm64.zip", "762e2dc875669566207a3c776a53dc6bb50770da25f90e1ab69fbc53e91f8da1"),
)
CORE_CATALOG: dict[str, CoreDescriptor] = {
    "xray": CoreDescriptor(
        "xray",
        "dicodePing + Xray",
        "Default integrated connection path.",
        "",
        "",
        "",
        "xray.exe" if _windows else "xray",
        0,
        "https://github.com/XTLS/Xray-core",
        "26.7.11",
    ),
    "psiphon": CoreDescriptor(
        "psiphon",
        "Psiphon tunnel core",
        "Psiphon local proxy core; a signed distribution configuration is required.",
        (
            "https://raw.githubusercontent.com/Psiphon-Labs/"
            "psiphon-tunnel-core-binaries/d0480af251596419915dd11b16be1d9ea72a9711/"
            "windows/psiphon-tunnel-core-i686.exe"
            if _windows
            else
            "https://raw.githubusercontent.com/Psiphon-Labs/"
            "psiphon-tunnel-core-binaries/fc06db4ef4919012f84d1f2d8644f8f85c2f779c/"
            "linux/psiphon-tunnel-core-x86_64"
        ),
        (
            "aec4c8221808227e8cfe50efcc9c6f18964fe8928a25b3d925973bff33b874b2"
            if _windows
            else "d06371a6c8a88728f1a154fd458a7b6bf5cfe3c854d126651e00740f97df0cdd"
        ),
        "binary",
        "psiphon-tunnel-core.exe" if _windows else "psiphon-tunnel-core",
        28 if _windows else 11,
        "https://github.com/Psiphon-Labs/psiphon-tunnel-core",
        "24b8381cc3",
    ),
    "aether": CoreDescriptor(
        "aether",
        "Aether 1.4 (Ironclad)",
        "MASQUE/WireGuard core with real-tunnel Ironclad validation.",
        "https://github.com/CluvexStudio/Aether/releases/download/v1.4.0/" + _aether_asset,
        _aether_sha,
        "zip" if _aether_asset.endswith(".zip") else "tar.gz",
        "aether.exe" if _windows else "aether",
        22,
        "https://github.com/CluvexStudio/Aether",
        "1.4.0",
    ),
    "warp": CoreDescriptor(
        "warp",
        "WARP / Usque",
        "Cloudflare WARP-compatible userspace tunnel powered by Usque.",
        "https://github.com/Diniboy1123/usque/releases/download/v4.2.1/" + _usque_asset,
        _usque_sha,
        "zip",
        "usque.exe" if _windows else "usque",
        6,
        "https://github.com/Diniboy1123/usque",
        "4.2.1",
    ),
}
_install_locks = {core_id: threading.Lock() for core_id in CORE_CATALOG}


def list_cores() -> list[CoreDescriptor]:
    return list(CORE_CATALOG.values())


def get_core(core_id: str) -> CoreDescriptor | None:
    return CORE_CATALOG.get(core_id)


def core_capability(core_id: str) -> tuple[CoreState, str]:
    if core_id == "xray":
        return CoreState.INSTALLED, "Built-in Xray core"
    if core_id == "psiphon" and not (core_dir("psiphon") / "client.config").is_file():
        return (
            CoreState.MISSING_AUTHORIZED_CONFIG,
            "Authorized Psiphon distribution configuration is unavailable in this build.",
        )
    if core_id not in CORE_CATALOG:
        return CoreState.UNSUPPORTED, "Unsupported in this build"
    return (
        (CoreState.INSTALLED, "Installed; upstream archive SHA-256 verified")
        if is_core_available(core_id)
        else (CoreState.NOT_INSTALLED, "Verified download is available")
    )


def core_dir(core_id: str) -> Path:
    return CORES_DIR / core_id


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_core_available(core_id: str) -> bool:
    if core_id == "xray":
        from .xray import find_xray
        return find_xray() is not None
    descriptor = get_core(core_id)
    if descriptor is None:
        return False
    bundled = BUNDLED_CORE_DIR / descriptor.executable_name
    if bundled.is_file() and (os.name == "nt" or os.access(bundled, os.X_OK)):
        return True
    executable = core_dir(core_id) / descriptor.executable_name
    metadata_path = core_dir(core_id) / "install.json"
    if not executable.is_file() or not metadata_path.is_file():
        return False
    if os.name != "nt" and not os.access(executable, os.X_OK):
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return (
            metadata.get("version") == descriptor.version
            and metadata.get("source_sha256") == descriptor.sha256
            and metadata.get("executable_sha256") == _sha256_of(executable)
        )
    except Exception:
        return False


def resolve_core_path(core_id: str) -> Path | None:
    if core_id == "xray":
        from .xray import find_xray
        return find_xray()
    descriptor = get_core(core_id)
    if descriptor is None:
        return None
    bundled = BUNDLED_CORE_DIR / descriptor.executable_name
    if bundled.is_file() and (os.name == "nt" or os.access(bundled, os.X_OK)):
        return bundled
    if not is_core_available(core_id):
        return None
    return core_dir(core_id) / descriptor.executable_name


def _download_file(
    url: str,
    target: Path,
    *,
    timeout: float = 120.0,
    progress: Callable[[int, int], None] | None = None,
    cancel_token: CancellationToken | threading.Event | None = None,
) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "dicodePing/1.9", "Accept": "application/octet-stream,*/*"},
    )
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_DOWNLOAD_HOSTS:
        raise RuntimeError("core URL is not on the approved HTTPS host list")

    class _SafeRedirect(urllib.request.HTTPRedirectHandler):
        def __init__(self) -> None:
            super().__init__()
            self.count = 0

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            self.count += 1
            host = (urllib.parse.urlparse(newurl).hostname or "").lower()
            if self.count > MAX_REDIRECTS or host not in ALLOWED_DOWNLOAD_HOSTS:
                raise RuntimeError("core download redirect was rejected")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SafeRedirect())
    started = time.monotonic()

    def _cancelled() -> bool:
        if cancel_token is None:
            return False
        method = getattr(cancel_token, "is_cancelled", None)
        return bool(method()) if callable(method) else bool(cancel_token.is_set())

    try:
        with opener.open(request, timeout=min(timeout, CONNECT_TIMEOUT_SECONDS)) as response, partial.open("wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("core download exceeds the safety limit")
            done = 0
            while True:
                if _cancelled():
                    raise RuntimeError("core download cancelled")
                if time.monotonic() - started > min(timeout, OVERALL_TIMEOUT_SECONDS):
                    raise TimeoutError("core download exceeded the overall timeout")
                try:
                    response.fp.raw._sock.settimeout(READ_TIMEOUT_SECONDS)  # type: ignore[attr-defined]
                except (AttributeError, OSError):
                    pass
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("core download exceeds the safety limit")
                output.write(chunk)
                if progress:
                    progress(done, total)
            if total and done != total:
                raise RuntimeError(f"core download length mismatch: expected {total}, got {done}")
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError("downloaded core is empty")
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _safe_destination(root: Path, member_name: str) -> Path:
    resolved_root = root.resolve()
    destination = (root / member_name).resolve()
    if destination != resolved_root and resolved_root not in destination.parents:
        raise RuntimeError(f"unsafe archive member: {member_name}")
    return destination


def _extract_archive(archive: Path, destination: Path, kind: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise RuntimeError("archive contains too many members")
            expanded = 0
            for member in members:
                _safe_destination(destination, member.filename)
                mode = (member.external_attr >> 16) & 0xFFFF
                if (mode & 0o170000) == 0o120000:
                    raise RuntimeError(f"archive links are not allowed: {member.filename}")
                if member.file_size > MAX_MEMBER_BYTES:
                    raise RuntimeError(f"archive member is too large: {member.filename}")
                expanded += member.file_size
                if member.compress_size and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
                    raise RuntimeError(f"suspicious compression ratio: {member.filename}")
            if expanded > MAX_EXPANDED_BYTES:
                raise RuntimeError("expanded archive exceeds the safety limit")
            for member in members:
                target = _safe_destination(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        return
    if kind == "tar.gz":
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise RuntimeError("archive contains too many members")
            expanded = 0
            for member in members:
                _safe_destination(destination, member.name)
                if member.issym() or member.islnk():
                    raise RuntimeError(f"archive links are not allowed: {member.name}")
                if member.size > MAX_MEMBER_BYTES:
                    raise RuntimeError(f"archive member is too large: {member.name}")
                expanded += member.size
            if expanded > MAX_EXPANDED_BYTES:
                raise RuntimeError("expanded archive exceeds the safety limit")
            bundle.extractall(destination, members=members, filter="data")
        return
    raise RuntimeError(f"unsupported core archive: {kind}")


def download_core(
    core_id: str,
    *,
    progress: Callable[[int, int], None] | None = None,
    stage: Callable[[str], None] | None = None,
    cancel_token: CancellationToken | threading.Event | None = None,
) -> Path:
    descriptor = get_core(core_id)
    if descriptor is None:
        raise RuntimeError(f"unknown core: {core_id}")
    if core_id == "xray":
        executable = resolve_core_path(core_id)
        if executable is None:
            raise RuntimeError("Xray core is not available")
        return executable
    capability, reason = core_capability(core_id)
    if capability in (CoreState.MISSING_AUTHORIZED_CONFIG, CoreState.UNSUPPORTED):
        raise RuntimeError(reason)
    if not descriptor.download_url or len(descriptor.sha256) != 64:
        raise RuntimeError(f"incomplete verified manifest for {core_id}")

    CORES_DIR.mkdir(parents=True, exist_ok=True)
    with _install_locks[core_id]:
        existing = resolve_core_path(core_id)
        if existing is not None:
            return existing
        staging = Path(tempfile.mkdtemp(prefix=f".{core_id}-", dir=str(CORES_DIR)))
        try:
            free = shutil.disk_usage(CORES_DIR).free
            if free < max(MIN_FREE_SPACE_BYTES, descriptor.size_hint_mb * 4 * 1024 * 1024):
                raise RuntimeError("not enough free disk space to install this core safely")
            if stage:
                stage(f"Downloading {descriptor.name}…")
            source = staging / ("core.bin" if descriptor.archive_kind == "binary" else "core.archive")
            _download_file(
                descriptor.download_url,
                source,
                progress=progress,
                cancel_token=cancel_token,
            )
            if stage:
                stage("Verifying SHA-256…")
            actual = _sha256_of(source)
            if actual != descriptor.sha256:
                raise RuntimeError(
                    f"integrity check failed for {core_id}: expected {descriptor.sha256}, got {actual}"
                )

            payload = staging / "payload"
            payload.mkdir()
            if descriptor.archive_kind == "binary":
                shutil.copy2(source, payload / descriptor.executable_name)
            else:
                if stage:
                    stage("Extracting verified core…")
                _extract_archive(source, payload, descriptor.archive_kind)
            executable = payload / descriptor.executable_name
            if not executable.is_file():
                raise RuntimeError(f"{descriptor.executable_name} is missing from the verified asset")
            if os.name != "nt":
                executable.chmod(0o755)
            self_test_args = ["--help"] if core_id == "warp" else ["--version"]
            self_test = subprocess.run(
                [str(executable), *self_test_args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=12,
                cwd=str(payload),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if self_test.returncode != 0:
                raise RuntimeError(f"{core_id} failed its version self-test")
            (payload / "install.json").write_text(
                json.dumps(
                    {
                        "core_id": core_id,
                        "version": descriptor.version,
                        "upstream": descriptor.upstream,
                        "source_url": descriptor.download_url,
                        "source_sha256": descriptor.sha256,
                        "executable_sha256": _sha256_of(executable),
                        "integrity": "SHA-256 verified",
                        "self_test": (self_test.stdout or self_test.stderr or "").strip()[:500],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            destination = core_dir(core_id)
            previous = CORES_DIR / f".{core_id}-previous"
            if destination.exists():
                shutil.rmtree(previous, ignore_errors=True)
                destination.replace(previous)
            try:
                payload.replace(destination)
            except Exception:
                if previous.exists() and not destination.exists():
                    previous.replace(destination)
                raise
            installed = destination / descriptor.executable_name
            LOGGER.info("Installed %s %s at %s", core_id, descriptor.version, installed)
            if stage:
                stage("Core ready")
            return installed
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def remove_core(core_id: str) -> None:
    if core_id == "xray":
        return
    with _install_locks.get(core_id, threading.Lock()):
        shutil.rmtree(core_dir(core_id), ignore_errors=True)
        if get_active_core() == core_id:
            set_active_core("xray")


def rollback_core(core_id: str) -> bool:
    """Atomically restore the single retained previous installation."""
    if core_id == "xray" or core_id not in CORE_CATALOG:
        return False
    with _install_locks[core_id]:
        destination = core_dir(core_id)
        previous = CORES_DIR / f".{core_id}-previous"
        if not previous.is_dir():
            return False
        failed = CORES_DIR / f".{core_id}-failed-{int(time.time())}"
        try:
            if destination.exists():
                destination.replace(failed)
            previous.replace(destination)
            shutil.rmtree(failed, ignore_errors=True)
            return is_core_available(core_id)
        except Exception:
            if failed.exists() and not destination.exists():
                failed.replace(destination)
            return False


def reverify_installed_cores() -> dict[str, bool]:
    """Verify installed payload hashes and quarantine corrupted installs."""
    result: dict[str, bool] = {}
    for core_id in CORE_CATALOG:
        if core_id == "xray":
            result[core_id] = is_core_available(core_id)
            continue
        destination = core_dir(core_id)
        if not destination.exists():
            result[core_id] = False
            continue
        valid = is_core_available(core_id)
        result[core_id] = valid
        if not valid:
            quarantine = CORES_DIR / f".{core_id}-corrupt-{int(time.time())}"
            try:
                destination.replace(quarantine)
                shutil.rmtree(quarantine, ignore_errors=True)
            except OSError:
                LOGGER.warning("Could not quarantine corrupt %s install", core_id)
    return result


def get_active_core() -> str:
    try:
        core_id = str(json.loads(ACTIVE_CORE_FILE.read_text(encoding="utf-8")).get("core_id"))
    except Exception:
        return "xray"
    return core_id if core_id in CORE_CATALOG else "xray"


def set_active_core(core_id: str) -> None:
    if core_id not in CORE_CATALOG:
        raise RuntimeError(f"unknown core: {core_id}")
    if core_id != "xray" and not is_core_available(core_id):
        raise RuntimeError(f"core '{core_id}' must be downloaded first")
    ACTIVE_CORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ACTIVE_CORE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"core_id": core_id}, indent=2), encoding="utf-8")
    temporary.replace(ACTIVE_CORE_FILE)


def run_core(
    core_id: str,
    args: list[str],
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = resolve_core_path(core_id)
    if executable is None:
        raise RuntimeError(f"core '{core_id}' is not available")
    return subprocess.run(
        [str(executable), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        cwd=str(executable.parent),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
