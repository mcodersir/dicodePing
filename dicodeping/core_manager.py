"""Runtime core download manager for dicodePing.

The user explicitly asked that no alternative cores (Psiphon, Aether,
etc.) be bundled in the build.  Instead, the user downloads them from
inside the app on first use.  This module manages that:

  * Each core has a ``CoreDescriptor`` with a download URL, a SHA-256
    digest, and a target path under ``DATA_DIR/cores/``.
  * ``download_core`` fetches the archive, verifies the digest, and
    extracts the executable.
  * ``is_core_available`` checks whether a core is already downloaded.
  * ``resolve_core_path`` returns the absolute path to the executable.

The actual download URLs and digests are configured in
``CORE_CATALOG`` below.  In a real release these would point to GitHub
release assets; for now they are placeholders that the user can edit
in settings.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .constants import DATA_DIR
from .diagnostics import get_logger

LOGGER = get_logger("core_manager")

CORES_DIR = DATA_DIR / "cores"
CORES_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class CoreDescriptor:
    """Metadata for a downloadable connection core."""

    id: str          # e.g. "xray", "psiphon", "aether"
    name: str        # human-readable
    description: str
    download_url: str
    sha256: str
    archive_kind: str  # "zip" or "tar.gz"
    executable_name: str  # e.g. "psiphon-tunnel-core.exe"
    size_hint_mb: int


# The default core (xray) is bundled with the build and never downloaded.
# The alternative cores are downloaded on first use.
CORE_CATALOG: dict[str, CoreDescriptor] = {
    "xray": CoreDescriptor(
        id="xray",
        name="Xray-core (built-in)",
        description="The default dicodePing core.  Already bundled with the app; no download required.",
        download_url="",
        sha256="",
        archive_kind="",
        executable_name="xray.exe" if os.name == "nt" else "xray",
        size_hint_mb=0,
    ),
    "psiphon": CoreDescriptor(
        id="psiphon",
        name="Psiphon tunnel core",
        description="Alternative connection core based on the Psiphon circumvention protocol.  Downloaded on first use.",
        # Placeholder — the real URL would point to a GitHub release asset.
        download_url="https://github.com/mcodersir/dicodePing/releases/download/cores-v1/psiphon-tunnel-core.zip",
        sha256="",
        archive_kind="zip",
        executable_name="psiphon-tunnel-core.exe" if os.name == "nt" else "psiphon-tunnel-core",
        size_hint_mb=12,
    ),
    "aether": CoreDescriptor(
        id="aether",
        name="Aether (Ironclad scan)",
        description="Alternative connection core with the Ironclad real-tunnel scan mode.  Downloaded on first use.",
        download_url="https://github.com/mcodersir/dicodePing/releases/download/cores-v1/aether-core.zip",
        sha256="",
        archive_kind="zip",
        executable_name="aether.exe" if os.name == "nt" else "aether",
        size_hint_mb=18,
    ),
}


def list_cores() -> list[CoreDescriptor]:
    """Return all known cores."""
    return list(CORE_CATALOG.values())


def get_core(core_id: str) -> CoreDescriptor | None:
    return CORE_CATALOG.get(core_id)


def core_dir(core_id: str) -> Path:
    return CORES_DIR / core_id


def is_core_available(core_id: str) -> bool:
    """Return True if the core's executable exists on disk."""
    if core_id == "xray":
        return True  # bundled
    desc = get_core(core_id)
    if not desc:
        return False
    exe = core_dir(core_id) / desc.executable_name
    return exe.exists() and (os.name == "nt" or os.access(exe, os.X_OK))


def resolve_core_path(core_id: str) -> Path | None:
    """Return the absolute path to the core's executable, or None."""
    if core_id == "xray":
        from .xray import find_xray
        return find_xray()
    desc = get_core(core_id)
    if not desc:
        return None
    exe = core_dir(core_id) / desc.executable_name
    if exe.exists():
        return exe
    return None


def _download_file(url: str, target: Path, *, timeout: float = 120.0,
                   progress: Callable[[int, int], None] | None = None) -> None:
    """Download ``url`` to ``target`` with optional progress callback."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "dicodePing/1.7",
            "Accept": "application/octet-stream,*/*",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with partial.open("wb") as output:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done, total)
    if partial.stat().st_size <= 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError("downloaded file is empty")
    partial.replace(target)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_archive(archive: Path, target_dir: Path, kind: str) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(target_dir)
    elif kind == "tar.gz":
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(target_dir)
    else:
        raise RuntimeError(f"unsupported archive kind: {kind}")


def download_core(
    core_id: str,
    *,
    progress: Callable[[int, int], None] | None = None,
    stage: Callable[[str], None] | None = None,
) -> Path:
    """Download, verify, and extract the given core.

    Returns the path to the extracted executable.  Raises ``RuntimeError``
    on any failure.
    """
    desc = get_core(core_id)
    if not desc:
        raise RuntimeError(f"unknown core: {core_id}")
    if core_id == "xray":
        path = resolve_core_path("xray")
        if path is None:
            raise RuntimeError("xray core is not available")
        return path
    if not desc.download_url:
        raise RuntimeError(
            f"core '{core_id}' has no download URL configured.  This is a placeholder; "
            "the real URL will be set in a future release."
        )

    if stage:
        stage(f"Downloading {desc.name}...")
    target_dir = core_dir(core_id)
    archive_path = target_dir / f"{core_id}.{desc.archive_kind}"
    _download_file(desc.download_url, archive_path, progress=progress)

    if desc.sha256:
        if stage:
            stage("Verifying integrity...")
        actual = _sha256_of(archive_path)
        if actual.lower() != desc.sha256.lower():
            archive_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"integrity check failed for {core_id}: expected {desc.sha256}, got {actual}"
            )

    if stage:
        stage("Extracting...")
    _extract_archive(archive_path, target_dir, desc.archive_kind)
    archive_path.unlink(missing_ok=True)

    exe = target_dir / desc.executable_name
    if not exe.exists():
        raise RuntimeError(
            f"extraction completed but executable '{desc.executable_name}' not found"
        )
    if os.name != "nt":
        try:
            exe.chmod(0o755)
        except Exception:
            pass
    LOGGER.info("Core %s downloaded and extracted to %s", core_id, exe)
    if stage:
        stage("Ready")
    return exe


def remove_core(core_id: str) -> None:
    """Delete a downloaded core."""
    if core_id == "xray":
        return  # bundled, never remove
    target_dir = core_dir(core_id)
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)


# --- Active core selection ---------------------------------------------

ACTIVE_CORE_FILE = DATA_DIR / "active_core.json"


def get_active_core() -> str:
    """Return the id of the currently active core (default: xray)."""
    try:
        data = json.loads(ACTIVE_CORE_FILE.read_text(encoding="utf-8"))
        return str(data.get("core_id") or "xray")
    except Exception:
        return "xray"


def set_active_core(core_id: str) -> None:
    """Set the active core.  The core must be available."""
    if core_id != "xray" and not is_core_available(core_id):
        raise RuntimeError(f"core '{core_id}' is not available; download it first")
    ACTIVE_CORE_FILE.write_text(
        json.dumps({"core_id": core_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Active core set to %s", core_id)


def run_core(core_id: str, args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run the given core with the given args and return the result."""
    exe = resolve_core_path(core_id)
    if exe is None:
        raise RuntimeError(f"core '{core_id}' is not available")
    return subprocess.run(
        [str(exe)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
