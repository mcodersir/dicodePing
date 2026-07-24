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
