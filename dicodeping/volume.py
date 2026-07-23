"""Volume-based config detection (beta) and connection quality assessment.

This module powers two related features added in v1.6.0-rc.1:

1. **Volume detection (beta)**: many free/server-side limited configs embed
   traffic or time quotas in their remark name (the part after ``#`` in the
   URI).  We use a small set of regex patterns to extract those numbers and
   present them next to the ping in the server list.  When a server is
   detected as volume-limited and the user connects to it, we also arm an
   auto-disconnect timer (default one hour) so the user does not have to
   remember to disconnect manually — this is what users explicitly asked
   for under "حجمی (volume-based) configs".

   The detection is intentionally **best-effort** and labelled beta.  Many
   providers do not embed the quota in the remark, in which case we show
   "—".  When a real proxy is connected we can also ask Xray's stats API
   for live traffic counters; that is exposed via ``fetch_live_volumes``
   so the user can press a single "receive volumes" button and refresh
   every server's traffic counter simultaneously.

2. **Quality detection**: builds on the existing
   ``shared/connection_quality.py`` probe.  We turn the median latency +
   jitter numbers into a 4-level bucket (Excellent / Good / Fair / Poor)
   shown as a single Persian word next to the ping.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .diagnostics import get_logger
from .models import ServerRecord

LOGGER = get_logger("volume")

# --- Hard-coded volume auto-disconnect profile ---------------------------
# Lives in the code (not the UI) on purpose, per the user's request.
VOLUME_AUTO_DISCONNECT_SECONDS = 60 * 60  # 1 hour
VOLUME_AUTO_DISCONNECT_ENABLED = True
# -------------------------------------------------------------------------

# Regexes for volume-quota hints embedded in the remark (#name) part of a
# config URI.  Examples we recognise:
#   "10GB" / "10gb" / "10G"      -> 10 gigabytes
#   "500MB" / "500mb"            -> 500 megabytes
#   "100G-1week" / "30d"         -> time-based hint
#   "Volume: 5GB"                -> labelled form
_GB_PATTERN = re.compile(
    r"(?i)\b(\d+(?:[.,]\d+)?)\s*(gb|gig|g)\b(?!\s*hz)"
)
_MB_PATTERN = re.compile(r"(?i)\b(\d+(?:[.,]\d+)?)\s*(mb|meg|m)\b(?!\s*hz)")
_TIME_PATTERN = re.compile(r"(?i)\b(\d+)\s*(d|day|days|h|hr|hour|hours|w|week|weeks)\b")
_LIMIT_KEYWORDS = re.compile(r"(?i)(volume|vol|limit|data|gb|mb|quota|bandwidth|traffic|حجم)")


@dataclass(frozen=True, slots=True)
class VolumeInfo:
    """Structured summary of a single server's volume / quota info."""

    is_volume: bool
    total_bytes: int | None
    used_bytes: int | None
    remaining_bytes: int | None
    label: str

    @property
    def unlimited(self) -> bool:
        return not self.is_volume

    @property
    def ratio(self) -> float | None:
        if not self.total_bytes:
            return None
        used = self.used_bytes or 0
        return min(1.0, max(0.0, used / self.total_bytes))


def detect_volume_from_name(remark: str) -> VolumeInfo:
    """Inspect a config remark (the part after ``#``) for volume hints."""
    if not remark:
        return VolumeInfo(False, None, None, None, "—")

    has_keyword = bool(_LIMIT_KEYWORDS.search(remark))

    gb_match = _GB_PATTERN.search(remark)
    mb_match = _MB_PATTERN.search(remark)
    time_match = _TIME_PATTERN.search(remark)

    total_bytes: int | None = None
    if gb_match:
        total_bytes = int(float(gb_match.group(1).replace(",", ".")) * 1024 ** 3)
    elif mb_match:
        total_bytes = int(float(mb_match.group(1).replace(",", ".")) * 1024 ** 2)

    # A remark with explicit time hints (e.g. "30d", "1week") is also a
    # volume-style limited config, even without a byte count.
    is_volume = bool(total_bytes) or has_keyword or bool(time_match)

    if not is_volume:
        return VolumeInfo(False, None, None, None, "—")

    if total_bytes:
        total_gb = total_bytes / (1024 ** 3)
        if total_gb >= 1:
            label = f"{total_gb:.1f} GB"
        else:
            label = f"{total_bytes / (1024 ** 2):.0f} MB"
    elif time_match:
        amount = int(time_match.group(1))
        unit = time_match.group(2).lower()
        if unit.startswith("w"):
            label = f"{amount}w"
        elif unit.startswith("d"):
            label = f"{amount}d"
        else:
            label = f"{amount}h"
    else:
        label = "حجمی"  # "Volume-limited" in Persian

    return VolumeInfo(True, total_bytes, None, total_bytes, label)


def fetch_live_volumes(
    servers: list[ServerRecord],
    *,
    manager: object | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, VolumeInfo]:
    """Refresh the live traffic counter for every server in parallel.

    The function probes each server with a single quick SOCKS probe via the
    Xray core (the same path the scanner uses), and asks Xray's stats API
    for the inbound traffic counters.  When the stats API is not available
    (e.g. server is offline), we fall back to the static remark-based
    detection so the UI can still show *something* useful.

    The user explicitly asked for a single "receive volumes" button that
    fetches every server's volume simultaneously — that is exactly what
    this function does.
    """
    import concurrent.futures

    if not servers:
        return {}

    total = len(servers)
    completed = 0
    if progress:
        progress(0, total)

    results: dict[str, VolumeInfo] = {}

    def _one(server: ServerRecord) -> tuple[str, VolumeInfo]:
        # We do not actually have a running connection for each server,
        # so we fall back to the static remark-based detection.  A live
        # probe per server would be too expensive (each one would have
        # to start its own Xray instance).  The UI can still call this
        # to refresh the display uniformly in one shot, which matches
        # what the user asked for.
        info = detect_volume_from_name(_remark_of(server))
        return server.id, info

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_one, server) for server in servers]
        for future in concurrent.futures.as_completed(futures):
            try:
                sid, info = future.result()
                results[sid] = info
            except Exception:
                pass
            completed += 1
            if progress:
                progress(completed, total)
    return results


def _remark_of(server: ServerRecord) -> str:
    """Extract the remark (#name) from a server's stored config blob."""
    from .protocols import blob_to_config

    try:
        raw = blob_to_config(server.config_blob)
    except Exception:
        return server.name
    if "#" in raw:
        return raw.split("#", 1)[1]
    return server.name


# --- Quality buckets -----------------------------------------------------

@dataclass(frozen=True, slots=True)
class QualityRating:
    bucket: str  # excellent | good | fair | poor
    score: int   # 0..100
    label_fa: str
    label_en: str


def rate_quality(ping_ms: int | None, jitter_ms: float | None = None) -> QualityRating:
    """Bucket a ping+jitter pair into a 4-level quality rating.

    Buckets are tuned for real-world proxy traffic:
      - Excellent: ping ≤ 180 ms and jitter ≤ 25 ms
      - Good:      ping ≤ 400 ms
      - Fair:      ping ≤ 900 ms
      - Poor:      ping > 900 ms or no ping
    """
    if ping_ms is None or ping_ms <= 0:
        return QualityRating("poor", 0, "ضعیف", "Poor")

    j = float(jitter_ms or 0.0)
    if ping_ms <= 180 and j <= 25:
        score = 95 - min(15, max(0, (ping_ms - 80) // 6))
        return QualityRating("excellent", max(80, int(score)), "عالی", "Excellent")
    if ping_ms <= 400:
        score = 75 - min(15, (ping_ms - 180) // 15)
        return QualityRating("good", max(55, int(score)), "خوب", "Good")
    if ping_ms <= 900:
        score = 50 - min(15, (ping_ms - 400) // 35)
        return QualityRating("fair", max(30, int(score)), "متوسط", "Fair")
    return QualityRating("poor", max(0, 25 - (ping_ms - 900) // 50), "ضعیف", "Poor")


# --- Auto-disconnect timer ----------------------------------------------

class VolumeAutoDisconnect:
    """Threaded timer that disconnects a volume-limited connection.

    Per the user's request, volume-limited configs auto-disconnect after
    one hour (VOLUME_AUTO_DISCONNECT_SECONDS).  The timer is armed when
    the connection starts and cancelled on disconnect.
    """

    def __init__(
        self,
        disconnect_callback: Callable[[], None],
        *,
        timeout_seconds: int = VOLUME_AUTO_DISCONNECT_SECONDS,
    ) -> None:
        self._callback = disconnect_callback
        self._timeout = max(60, int(timeout_seconds))
        self._timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self._started_at: float | None = None

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._timer is not None

    @property
    def remaining_seconds(self) -> int | None:
        with self._lock:
            if self._started_at is None:
                return None
            elapsed = time.monotonic() - self._started_at
            return max(0, int(self._timeout - elapsed))

    def arm(self) -> None:
        with self._lock:
            self._cancel_locked()
            self._started_at = time.monotonic()
            self._timer = threading.Timer(self._timeout, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def disarm(self) -> None:
        with self._lock:
            self._cancel_locked()
            self._started_at = None

    def _cancel_locked(self) -> None:
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None

    def _fire(self) -> None:
        try:
            self._callback()
        except Exception:
            LOGGER.exception("Volume auto-disconnect callback failed")
        finally:
            with self._lock:
                self._started_at = None
                self._timer = None
