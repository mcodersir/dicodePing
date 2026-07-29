from __future__ import annotations

import statistics
from typing import Iterable


# A successful TCP handshake can genuinely be below 20 ms on a nearby relay.
# Do not discard it: v2rayNG-style delay tests show the measured delay and
# leave the caller to decide whether that server is suitable for auto-select.
MIN_VALID_LATENCY_MS = 1
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
