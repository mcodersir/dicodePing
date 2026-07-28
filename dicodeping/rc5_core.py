from __future__ import annotations

from collections.abc import Iterable


def auto_retry_ids(rows: Iterable[object], limit: int = 5) -> list[str]:
    """Return a bounded, de-duplicated retry plan in service ranking order."""
    result: list[str] = []
    for row in rows:
        server_id = str(getattr(row, "id", "") or "")
        if server_id and server_id not in result:
            result.append(server_id)
        if len(result) >= max(1, limit):
            break
    return result


def connection_lost_message(language: str, server_name: str = "") -> str:
    name = str(server_name or "").strip()
    if language == "en":
        return f"Connection to {name} was interrupted." if name else "The connection was interrupted."
    return f"اتصال به {name} قطع شد." if name else "اتصال به‌طور غیرمنتظره قطع شد."
