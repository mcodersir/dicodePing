from __future__ import annotations

from .rc2_core import clean_display_name
from .rc3_core import trusted_latency


def usable_for_auto(status: str, ping_ms: int | None) -> bool:
    """Auto-selection depends on a live endpoint probe, not an IP-geo guess."""
    return str(status).casefold() == "online" and trusted_latency(ping_ms)


def preferred_display_name(config_name: str, fallback: str) -> str:
    """Keep the subscription's explicit name; only synthesize a last-resort label."""
    return clean_display_name(config_name) or clean_display_name(fallback)
