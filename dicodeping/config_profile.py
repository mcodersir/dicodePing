"""Conservative, display-only config profile hints.

These labels never claim a measured quota or lifetime. They are emitted only
when the config's own remark or hostname contains an explicit signal.
"""
from __future__ import annotations

import re
from urllib.parse import unquote


def classify_config_profile(raw: str, host: str = "") -> str:
    text = unquote(raw).casefold()
    hostname = host.casefold()
    if (
        hostname.endswith((".workers.dev", ".pages.dev"))
        or "cloudflare worker" in text
        or "cloudflare-worker" in text
        or re.search(r"\b(worker|workers)\b", text)
    ):
        return "worker"
    if re.search(r"(?:\d+(?:[.,]\d+)?)\s*(?:gb|mb|tb)\b", text) or any(
        token in text for token in ("quota", "volume", "limited", "حجمی", "حجم")
    ):
        return "limited"
    if any(token in text for token in ("permanent", "unlimited", "دائمی", "نامحدود")):
        return "persistent"
    return "unknown"
