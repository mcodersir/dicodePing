"""Real volume detection and connection quality assessment.

This module powers two related features:

1. **Real volume detection**: many subscription providers expose the
   user's traffic quota via the standard ``Subscription-Userinfo``
   HTTP header (used by v2rayN, Nekoray, etc.) when the subscription
   is downloaded.  The header looks like::

       Subscription-Userinfo: upload=4567; download=1234567; total=10737418240; expire=1712345678

   We cache the most recent header per source URL and use it to compute
   the remaining quota.  When the user taps "Fetch Volumes" the scanner
   re-downloads every enabled source's HEAD request in parallel, parses
   the header, and updates the cached quota.  This is the *real*
   remaining-volume number that the user asked for in v1.6.0-rc.2.

   For per-server live traffic (during an active connection) we also
   query Xray's stats API.  That path is already wired into
   ``XrayManager.traffic_stats`` and is reused here without changes.

2. **Quality detection**: builds on the existing
   ``shared/connection_quality.py`` probe.  We turn the median latency +
   jitter numbers into a 4-level bucket (Excellent / Good / Fair / Poor)
   shown as a single Persian word next to the ping.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from .diagnostics import get_logger
from .models import ServerRecord

LOGGER = get_logger("volume")

# --- Hard-coded volume auto-disconnect profile ---------------------------
VOLUME_AUTO_DISCONNECT_SECONDS = 60 * 60  # 1 hour
VOLUME_AUTO_DISCONNECT_ENABLED = True
# -------------------------------------------------------------------------

# --- Remark-based heuristic ---------------------------------------------
# Used as a *fallback* when no real Subscription-Userinfo header is
# available.  Many free servers embed a quota hint in the remark (#name).
_GB_PATTERN = re.compile(r"(?i)\b(\d+(?:[.,]\d+)?)\s*(gb|gig|g)\b(?!\s*hz)")
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
    source: str  # "subscription-header" | "remark" | "live-stats" | "none"

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
    """Inspect a config remark (the part after ``#``) for volume hints.

    Used as a fallback when no real subscription-header data is available.
    """
    if not remark:
        return VolumeInfo(False, None, None, None, "—", "none")

    has_keyword = bool(_LIMIT_KEYWORDS.search(remark))
    gb_match = _GB_PATTERN.search(remark)
    mb_match = _MB_PATTERN.search(remark)
    time_match = _TIME_PATTERN.search(remark)

    total_bytes: int | None = None
    if gb_match:
        total_bytes = int(float(gb_match.group(1).replace(",", ".")) * 1024 ** 3)
    elif mb_match:
        total_bytes = int(float(mb_match.group(1).replace(",", ".")) * 1024 ** 2)

    is_volume = bool(total_bytes) or has_keyword or bool(time_match)
    if not is_volume:
        return VolumeInfo(False, None, None, None, "—", "none")

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
        label = "حجمی"

    return VolumeInfo(True, total_bytes, None, total_bytes, label, "remark")


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


# --- Subscription-Userinfo header parsing -------------------------------

_SUB_HEADER_RE = re.compile(
    r"upload\s*=\s*(\d+)\s*;\s*download\s*=\s*(\d+)\s*;\s*total\s*=\s*(\d+)"
    r"(?:\s*;\s*expire\s*=\s*(\d+))?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SubscriptionQuota:
    """Parsed values from a ``Subscription-Userinfo`` HTTP header."""

    upload_bytes: int
    download_bytes: int
    total_bytes: int
    expire_unix: int | None

    @property
    def used_bytes(self) -> int:
        return self.upload_bytes + self.download_bytes

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.total_bytes - self.used_bytes)

    @property
    def ratio(self) -> float:
        if not self.total_bytes:
            return 0.0
        return min(1.0, max(0.0, self.used_bytes / self.total_bytes))

    @property
    def expire_dt(self) -> datetime | None:
        if not self.expire_unix:
            return None
        try:
            return datetime.fromtimestamp(self.expire_unix, tz=timezone.utc)
        except (OSError, ValueError):
            return None


def parse_subscription_userinfo(header_value: str) -> SubscriptionQuota | None:
    """Parse a ``Subscription-Userinfo`` header value.

    Returns ``None`` if the header is missing or malformed.
    """
    if not header_value:
        return None
    match = _SUB_HEADER_RE.search(header_value)
    if not match:
        return None
    try:
        upload = int(match.group(1))
        download = int(match.group(2))
        total = int(match.group(3))
        expire = int(match.group(4)) if match.group(4) else None
    except (TypeError, ValueError):
        return None
    return SubscriptionQuota(upload, download, total, expire)


def fetch_subscription_quota(url: str, *, timeout: float = 8.0) -> SubscriptionQuota | None:
    """Issue a request to a subscription URL and parse the quota header.

    The request goes through the system's current proxy (which, during a
    scan, is the program's own VPN).  This is the *real* way to get the
    remaining-volume number that the user asked for.

    We try HEAD first; if the server rejects HEAD (some subscription
    providers only honour GET), we fall back to a tiny ranged GET so we
    still get the headers without downloading the whole body.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        return None

    def _try(method: str, *, add_range: bool = False) -> str | None:
        try:
            request = urllib.request.Request(url, method=method)
            request.add_header("User-Agent", "dicodePing-Scanner/1.6")
            if add_range:
                request.add_header("Range", "bytes=0-0")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.headers.get("Subscription-Userinfo")
        except Exception as exc:
            LOGGER.debug("Subscription quota fetch (%s) failed for %s: %s", method, url, exc)
            return None

    header_value = _try("HEAD")
    if not header_value:
        header_value = _try("GET", add_range=True)
    if not header_value:
        return None
    return parse_subscription_userinfo(header_value)


# --- Per-source quota cache ---------------------------------------------

_QUOTA_CACHE: dict[str, tuple[SubscriptionQuota, float]] = {}
_QUOTA_CACHE_TTL = 5 * 60  # 5 minutes


def cache_quota(source_url: str, quota: SubscriptionQuota) -> None:
    _QUOTA_CACHE[source_url] = (quota, time.monotonic())


def get_cached_quota(source_url: str) -> SubscriptionQuota | None:
    entry = _QUOTA_CACHE.get(source_url)
    if not entry:
        return None
    quota, ts = entry
    if time.monotonic() - ts > _QUOTA_CACHE_TTL:
        return None
    return quota


# --- Batch refresh ------------------------------------------------------

def fetch_live_volumes(
    servers: list[ServerRecord],
    *,
    source_urls: dict[str, str] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, VolumeInfo]:
    """Refresh volume info for every server in one shot.

    Args:
        servers: The saved server list.  For each server we compute a
            ``VolumeInfo`` based on:
              1. The cached ``Subscription-Userinfo`` of its source URL
                 (if available).
              2. The remark-based heuristic as a fallback.
        source_urls: A mapping of ``source_id -> source_url``.  If
            provided, the function also re-fetches each unique source
            URL's HEAD in parallel and updates the cache.  If omitted,
            only the cache + remark heuristic are used.
        progress: Optional callback ``(done, total)``.
    """
    import concurrent.futures

    if not servers:
        return {}

    total = len(servers)
    completed = 0
    if progress:
        progress(0, total)

    # Step 1: refresh source quotas in parallel if URLs were provided.
    if source_urls:
        unique_urls = list({url for url in source_urls.values() if url})
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            future_to_url = {
                pool.submit(fetch_subscription_quota, url): url for url in unique_urls
            }
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    quota = future.result()
                except Exception:
                    quota = None
                if quota is not None:
                    cache_quota(url, quota)

    # Step 2: compute a VolumeInfo per server.
    results: dict[str, VolumeInfo] = {}
    for server in servers:
        # Look up the source URL.
        source_url = (source_urls or {}).get(server.source_id, "")
        quota = get_cached_quota(source_url) if source_url else None
        if quota is not None:
            used = quota.used_bytes
            total_b = quota.total_bytes
            remaining = quota.remaining_bytes
            label = format_volume_label(used, total_b, remaining, quota.expire_dt)
            info = VolumeInfo(
                is_volume=True,
                total_bytes=total_b,
                used_bytes=used,
                remaining_bytes=remaining,
                label=label,
                source="subscription-header",
            )
        else:
            info = detect_volume_from_name(_remark_of(server))
        results[server.id] = info
        completed += 1
        if progress:
            progress(completed, total)
    return results


def format_volume_label(
    used: int,
    total: int,
    remaining: int,
    expire: datetime | None,
) -> str:
    """Render a short human-readable label like ``3.2 / 10.0 GB``."""
    def _gb(value: int) -> str:
        gb = value / (1024 ** 3)
        if gb >= 1:
            return f"{gb:.1f} GB"
        return f"{value / (1024 ** 2):.0f} MB"

    parts: list[str] = []
    if total > 0:
        parts.append(f"{_gb(used)} / {_gb(total)}")
    else:
        parts.append("نامحدود")
    if remaining > 0 and remaining < total:
        parts.append(f"({_gb(remaining)} باقی)")
    if expire:
        now = datetime.now(timezone.utc)
        days_left = (expire - now).days
        if days_left > 0:
            parts.append(f"{days_left}d")
    return " • ".join(parts)


# --- Quality buckets -----------------------------------------------------

@dataclass(frozen=True, slots=True)
class QualityRating:
    bucket: str  # excellent | good | fair | poor
    score: int   # 0..100
    label_fa: str
    label_en: str


def rate_quality(ping_ms: int | None, jitter_ms: float | None = None) -> QualityRating:
    """Bucket a ping+jitter pair into a 4-level quality rating."""
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
    """Threaded timer that disconnects a volume-limited connection."""

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
