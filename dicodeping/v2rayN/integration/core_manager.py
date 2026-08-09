"""v2rayN-based core management layer for dicodePing Version 3.

Handles core download, verification, lifecycle, and the active core
tracking for the v2rayN stack integration.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
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
from dicodeping.diagnostics import get_logger
from dicodeping.core_runtime import CancellationToken, CoreState

LOGGER = get_logger("core_manager")

CORES_DIR = DATA_DIR / "cores"
ACTIVE_CORE_FILE = DATA_DIR / "active_core.json"
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 128
MAX_EXPANDED_BYTES = 350 * 1024 * 1024
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


_core = {}
_core_lock = threading.Lock()


def list_cores() -> list[CoreDescriptor]:
    """Return all available core descriptors."""
    return list(_core.values())


def get_core(core_id: str) -> CoreDescriptor | None:
    """Return the descriptor for a specific core, or None if unavailable."""
    return _core.get(core_id)


def core_capability(core_id: str) -> tuple[CoreState, str]:
    """Return the capability state and reason for a core."""
    if core_id == "xray":
        return CoreState.INSTALLED, "Built-in Xray core"
    descriptor = get_core(core_id)
    if descriptor is None:
        return CoreState.UNSUPPORTED, "Unsupported in this build"
    return (CoreState.INSTALLED, "Installed; upstream archive SHA-256 verified")


def core_dir(core_id: str) -> Path:
    """Return the directory for a specific core."""
    return CORES_DIR / core_id


def _sha256_of(path: Path) -> str:
    """Compute the SHA-256 hash of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_core_available(core_id: str) -> bool:
    """Check whether a core is installed, downloaded, and verified."""
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
    """Return the path to the executable for a core, or None."""
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
    """Download a file from URL with progress tracking and SHA-256 verification."""
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
                    response.fp.raw._sock.settimeout(READ_TIMEOUT_SECONDS)
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
    """Resolve and validate a destination path within an archive."""
    resolved_root = root.resolve()
    destination = (root / member_name).resolve()
    if destination != resolved_root and resolved_root not in destination.parents:
        raise RuntimeError(f"unsafe archive member: {member_name}")
    return destination


def _extract_archive(archive: Path, destination: Path, kind: str) -> None:
    """Extract an archive to a destination directory."""
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
    """Download and install a core (Xray, Wintun, etc.).

    Returns the path to the installed core executable.
    """
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
    with _core_lock[core_id]:
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
    """Remove a core installation."""
    if core_id == "xray":
        return
    with _core_lock[core_id]:
        shutil.rmtree(core_dir(core_id), ignore_errors=True)
        if get_active_core() == core_id:
            set_active_core("xray")


def rollback_core(core_id: str) -> bool:
    """Atomically restore the single retained previous installation."""
    if core_id == "xray" or core_id not in _core:
        return False
    with _core_lock[core_id]:
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
    for core_id in _core:
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
    """Return the ID of the currently active core."""
    try:
        core_id = str(json.loads(ACTIVE_CORE_FILE.read_text(encoding="utf-8")).get("core_id"))
    except Exception:
        return "xray"
    return core_id if core_id in _core else "xray"


def set_active_core(core_id: str) -> None:
    """Set the active core."""
    if core_id not in _core:
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
    """Run a core process with the given arguments."""
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
    )