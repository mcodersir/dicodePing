"""Verified, on-demand connection-core installation.

Alternative cores are deliberately excluded from the application bundle.  This
module downloads immutable upstream assets, verifies SHA-256 before extraction,
prevents archive traversal, and atomically installs one version per core.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .constants import DATA_DIR
from .diagnostics import get_logger

LOGGER = get_logger("core_manager")
CORES_DIR = DATA_DIR / "cores"
ACTIVE_CORE_FILE = DATA_DIR / "active_core.json"
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024


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
        "https://github.com/shirokhorshid/psiphon-tunnel-core",
        "24b8381cc3",
    ),
    "aether": CoreDescriptor(
        "aether",
        "Aether 1.4 (Ironclad)",
        "MASQUE/WireGuard core with real-tunnel Ironclad validation.",
        "https://github.com/CluvexStudio/Aether/releases/download/v1.4.0/"
        + ("aether-windows-x86_64.zip" if _windows else "aether-linux-x86_64.tar.gz"),
        (
            "4b4ac4c2dcade01c13bc6f1706f7f62e94c3b3058184212692bd9d598c0ce9b4"
            if _windows
            else "683dc190a948e8555fc9738ef2d1be403d95606e191e75f0e6941012c6b869cd"
        ),
        "zip" if _windows else "tar.gz",
        "aether.exe" if _windows else "aether",
        22,
        "https://github.com/CluvexStudio/Aether",
        "1.4.0",
    ),
}
_install_locks = {core_id: threading.Lock() for core_id in CORE_CATALOG}


def list_cores() -> list[CoreDescriptor]:
    return list(CORE_CATALOG.values())


def get_core(core_id: str) -> CoreDescriptor | None:
    return CORE_CATALOG.get(core_id)


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
    if descriptor is None or not is_core_available(core_id):
        return None
    return core_dir(core_id) / descriptor.executable_name


def _download_file(
    url: str,
    target: Path,
    *,
    timeout: float = 120.0,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "dicodePing/1.8", "Accept": "application/octet-stream,*/*"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response, partial.open("wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("core download exceeds the safety limit")
            done = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("core download exceeds the safety limit")
                output.write(chunk)
                if progress:
                    progress(done, total)
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
            for member in bundle.infolist():
                _safe_destination(destination, member.filename)
                if member.file_size > MAX_MEMBER_BYTES:
                    raise RuntimeError(f"archive member is too large: {member.filename}")
            bundle.extractall(destination)
        return
    if kind == "tar.gz":
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                _safe_destination(destination, member.name)
                if member.issym() or member.islnk():
                    raise RuntimeError(f"archive links are not allowed: {member.name}")
                if member.size > MAX_MEMBER_BYTES:
                    raise RuntimeError(f"archive member is too large: {member.name}")
            bundle.extractall(destination, members=members, filter="data")
        return
    raise RuntimeError(f"unsupported core archive: {kind}")


def download_core(
    core_id: str,
    *,
    progress: Callable[[int, int], None] | None = None,
    stage: Callable[[str], None] | None = None,
) -> Path:
    descriptor = get_core(core_id)
    if descriptor is None:
        raise RuntimeError(f"unknown core: {core_id}")
    if core_id == "xray":
        executable = resolve_core_path(core_id)
        if executable is None:
            raise RuntimeError("Xray core is not available")
        return executable
    if not descriptor.download_url or len(descriptor.sha256) != 64:
        raise RuntimeError(f"incomplete verified manifest for {core_id}")

    CORES_DIR.mkdir(parents=True, exist_ok=True)
    with _install_locks[core_id]:
        existing = resolve_core_path(core_id)
        if existing is not None:
            return existing
        staging = Path(tempfile.mkdtemp(prefix=f".{core_id}-", dir=str(CORES_DIR)))
        try:
            if stage:
                stage(f"Downloading {descriptor.name}…")
            source = staging / ("core.bin" if descriptor.archive_kind == "binary" else "core.archive")
            _download_file(descriptor.download_url, source, progress=progress)
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
            (payload / "install.json").write_text(
                json.dumps(
                    {
                        "core_id": core_id,
                        "version": descriptor.version,
                        "upstream": descriptor.upstream,
                        "source_url": descriptor.download_url,
                        "source_sha256": descriptor.sha256,
                        "executable_sha256": _sha256_of(executable),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            destination = core_dir(core_id)
            previous = CORES_DIR / f".{core_id}-previous"
            shutil.rmtree(previous, ignore_errors=True)
            if destination.exists():
                destination.replace(previous)
            try:
                payload.replace(destination)
            except Exception:
                if previous.exists() and not destination.exists():
                    previous.replace(destination)
                raise
            shutil.rmtree(previous, ignore_errors=True)
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
