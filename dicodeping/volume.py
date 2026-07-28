"""Connection quality assessment (v1.7.0-rc.1).

The volume detection feature was removed in v1.7.0-rc.1 per the user's
request.  This module now only provides the quality rating helper that
the Servers page uses to colour-code the ping cell.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QualityRating:
    bucket: str  # excellent | good | fair | poor
    score: int   # 0..100
    label_fa: str
    label_en: str


def rate_quality(ping_ms: int | None, jitter_ms: float | None = None, failures: int = 0) -> QualityRating:
    """Bucket a ping+jitter+failures triple into a 4-level quality rating.

    v1.7.0-rc.2: improved algorithm that accounts for jitter (from ICMP
    samples), failure history, and uses more realistic thresholds for
    proxy traffic.

    Buckets:
      - Excellent: ping <= 150ms, jitter <= 20ms, 0 failures
      - Good:      ping <= 350ms, jitter <= 50ms, <= 2 failures
      - Fair:      ping <= 800ms, jitter <= 100ms, <= 5 failures
      - Poor:      ping > 800ms or no ping or too many failures
    """
    if ping_ms is None or ping_ms <= 0:
        return QualityRating("poor", 0, "ضعیف", "Poor")

    j = float(jitter_ms or 0.0)
    f = min(10, max(0, failures))

    # Combined score: start from 100, deduct for high ping, jitter, failures.
    score = 100
    # Ping deduction: 0-150ms = 0, 150-350ms = -20, 350-800ms = -40, 800+ = -70
    if ping_ms > 800:
        score -= 70
    elif ping_ms > 350:
        score -= 40 + min(15, (ping_ms - 350) // 30)
    elif ping_ms > 150:
        score -= 20 + min(15, (ping_ms - 150) // 15)
    # Jitter deduction: 0-20ms = 0, 20-50ms = -10, 50-100ms = -20, 100+ = -35
    if j > 100:
        score -= 35
    elif j > 50:
        score -= 20
    elif j > 20:
        score -= 10
    # Failure deduction: -5 per failure, max -30
    score -= min(30, f * 5)
    score = max(0, min(100, score))

    if ping_ms <= 150 and j <= 20 and f == 0:
        return QualityRating("excellent", max(85, score), "عالی", "Excellent")
    if ping_ms <= 350 and j <= 50 and f <= 2:
        return QualityRating("good", max(55, score), "خوب", "Good")
    if ping_ms <= 800 and j <= 100 and f <= 5:
        return QualityRating("fair", max(25, score), "متوسط", "Fair")
    return QualityRating("poor", score, "ضعیف", "Poor")


# --- Auto-disconnect timer (kept for backward compat; harmless no-op) ---

import threading
import time
from typing import Callable


class VolumeAutoDisconnect:
    """Backward-compat stub.  Volume detection was removed in v1.7.0-rc.1.

    This class is kept so that older UI code that references it does not
    break.  All methods are no-ops.
    """

    def __init__(
        self,
        disconnect_callback: Callable[[], None],
        *,
        timeout_seconds: int = 3600,
    ) -> None:
        self._callback = disconnect_callback
        self._timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self._started_at: float | None = None

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._timer is not None

    @property
    def remaining_seconds(self) -> int | None:
        return None

    def arm(self) -> None:
        # No-op in v1.7.0-rc.1.
        pass

    def disarm(self) -> None:
        with self._lock:
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None
            self._started_at = None
