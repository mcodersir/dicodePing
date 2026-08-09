from __future__ import annotations

import time


class StartupGate:
    """Allow exactly one startup path (worker or watchdog) to open the UI."""

    def __init__(self) -> None:
        self.completed = False

    def claim(self) -> bool:
        if self.completed:
            return False
        self.completed = True
        return True


def server_refresh_due(
    cached_count: int,
    last_refresh: object,
    *,
    now: float | None = None,
    interval_seconds: int,
) -> bool:
    if cached_count <= 0:
        return True
    try:
        last = float(last_refresh or 0)
    except (TypeError, ValueError):
        return True
    current = time.time() if now is None else float(now)
    return last <= 0 or current - last >= max(1, interval_seconds)


def startup_rows(value: object, limit: int = 320) -> list[object]:
    if not isinstance(value, list):
        return []
    return list(value[: max(0, limit)])
