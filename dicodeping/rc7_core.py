from __future__ import annotations

from collections.abc import Iterable


def bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def batches(rows: Iterable[object], page_size: int) -> list[list[object]]:
    values = list(rows)
    size = max(1, page_size)
    return [values[index : index + size] for index in range(0, len(values), size)]


def auto_score(row: object) -> tuple[int, int, int, str]:
    ping = int(getattr(row, "ping_ms", 999_999) or 999_999)
    failures = max(0, int(getattr(row, "failures", 0) or 0))
    favorite_penalty = -40 if bool(getattr(row, "favorite", False)) else 0
    return ping + failures * 220 + favorite_penalty, failures, ping, str(getattr(row, "id", ""))


def diverse_auto_candidates(rows: Iterable[object], limit: int = 8) -> list[object]:
    ranked = sorted(rows, key=auto_score)
    result: list[object] = []
    used: set[tuple[str, int]] = set()
    for row in ranked:
        endpoint = (str(getattr(row, "host", "")), int(getattr(row, "port", 0) or 0))
        if endpoint in used:
            continue
        used.add(endpoint)
        result.append(row)
        if len(result) >= max(1, limit):
            break
    return result
