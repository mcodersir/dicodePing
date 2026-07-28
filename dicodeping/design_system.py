"""Shared RC2 UI design tokens and deterministic responsive rules."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WindowClass(str, Enum):
    COMPACT = "compact"
    MEDIUM = "medium"
    EXPANDED = "expanded"


@dataclass(frozen=True)
class DesignTokens:
    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24
    radius_sm: int = 8
    radius_md: int = 12
    radius_lg: int = 16
    control_height: int = 44
    touch_target: int = 48
    content_max_width: int = 1440
    compact_breakpoint: int = 900
    expanded_breakpoint: int = 1180


TOKENS = DesignTokens()


def window_class(width: int) -> WindowClass:
    if width < TOKENS.compact_breakpoint:
        return WindowClass.COMPACT
    if width < TOKENS.expanded_breakpoint:
        return WindowClass.MEDIUM
    return WindowClass.EXPANDED


def desktop_server_columns(width: int) -> dict[int, bool]:
    """Visibility for country/name/location/ip/TCP/Xray/quality/pin/action."""
    mode = window_class(width)
    if mode is WindowClass.COMPACT:
        return {index: False for index in range(9)}
    if mode is WindowClass.MEDIUM:
        return {0: True, 1: True, 2: False, 3: False, 4: True, 5: True, 6: True, 7: True, 8: True}
    return {index: True for index in range(9)}
