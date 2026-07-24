"""Time-to-completion (ETA) estimator for long-running UI stages.

Used by the splash screen, the ping/fetch stages, and the scanner so the
user can see how long the current operation is expected to take.

The estimator is intentionally simple: it keeps a sliding window of the
last few (current, total) samples, computes the average items-per-second
rate, and divides the remaining items by that rate.  The result is
clamped to ``[min_seconds, max_seconds]`` to avoid wild swings at the
start of an operation.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class ETASample:
    """A single (current, total, timestamp) observation."""

    current: int
    total: int
    timestamp: float


class ETAEstimator:
    """Sliding-window moving-average ETA estimator."""

    def __init__(
        self,
        *,
        window: int = 6,
        min_seconds: int = 1,
        max_seconds: int = 999,
        warmup_seconds: float = 0.4,
    ) -> None:
        self._samples: deque[ETASample] = deque(maxlen=max(2, window))
        self._min = max(0, min_seconds)
        self._max = max(self._min, max_seconds)
        self._warmup = max(0.0, warmup_seconds)
        self._start: float | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._start = None

    def update(self, current: int, total: int, *, now: float | None = None) -> None:
        ts = now if now is not None else time.monotonic()
        if self._start is None:
            self._start = ts
        self._samples.append(ETASample(current=max(0, current), total=max(0, total), timestamp=ts))

    @property
    def started_at(self) -> float | None:
        return self._start

    @property
    def elapsed_seconds(self) -> float:
        if self._start is None:
            return 0.0
        return max(0.0, time.monotonic() - self._start)

    def remaining_seconds(self) -> int | None:
        """Return the estimated seconds remaining, or ``None`` if unknown.

        Returns ``None`` when there are fewer than two samples, when the
        total is zero, or when the operation has not yet left the warm-up
        period (the first few hundred milliseconds give wildly inaccurate
        rates).
        """
        if len(self._samples) < 2:
            return None
        first = self._samples[0]
        last = self._samples[-1]
        if last.total <= 0:
            return None
        if last.current >= last.total:
            return 0
        dt = last.timestamp - first.timestamp
        if dt < self._warmup:
            return None
        done_in_window = max(0, last.current - first.current)
        if done_in_window <= 0:
            # No progress in the window — fall back to elapsed-so-far
            # projected linearly from start.
            elapsed = last.timestamp - (self._start or first.timestamp)
            if elapsed <= 0 or last.current <= 0:
                return None
            rate = last.current / elapsed
        else:
            rate = done_in_window / dt
        if rate <= 0:
            return self._max
        remaining_items = max(0, last.total - last.current)
        eta = remaining_items / rate
        return max(self._min, min(self._max, int(round(eta))))

    def progress_percent(self) -> int:
        if not self._samples:
            return 0
        last = self._samples[-1]
        if last.total <= 0:
            return 0
        return max(0, min(100, int(round(last.current * 100 / last.total))))


def format_seconds(seconds: int | None) -> str:
    """Render a seconds count as a short human-readable string.

    Examples: ``None -> "—"``; ``0 -> "0s"``; ``45 -> "45s"``;
    ``90 -> "1:30"``; ``3725 -> "1:02:05"``.
    """
    if seconds is None:
        return "—"
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}:{seconds % 60:02d}"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"
