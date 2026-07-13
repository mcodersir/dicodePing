from __future__ import annotations

import statistics
from typing import Iterable


MIN_VALID_LATENCY_MS = 20
MAX_VALID_LATENCY_MS = 5000


def median_latency(samples: Iterable[int | float | None]) -> int | None:
    values = [float(value) for value in samples if value is not None and 0 < float(value) <= MAX_VALID_LATENCY_MS]
    if not values:
        return None
    return max(1, int(round(statistics.median(values))))


def trusted_latency(value: int | None, minimum: int = MIN_VALID_LATENCY_MS) -> bool:
    return value is not None and minimum <= value <= MAX_VALID_LATENCY_MS


def display_latency(value: int | None) -> str:
    return f"{value} ms" if trusted_latency(value) else "—"
