"""v2rayN integration layer for dicodePing Version 3.

This package provides a clean integration layer that replaces the legacy
Python networking wrapper with a proper v2rayN-based implementation.

Modules:
    - net: DNS resolution, proxy handling, connectivity probes
    - xray: Xray core operations (download, verification, TUN management)
    - core_manager: Core download, verification, lifecycle management
    - connection_manager: Connection lifecycle with WARP registration
    - service: ServerService with build_and_save, refresh_saved, auto_candidates
    - discovery: Discovery with subscription fetching and parsing
    - protocols: Protocol parsing for v2rayN formats (vless, vmess, trojan, ss)
    - models: Data models (ServerRecord, Endpoint, SourceDefinition)
    - ui: Modern PySide6 Qt UI layer with redesigned interface
"""
from __future__ import annotations

from .models import ServerRecord, Endpoint, SourceDefinition, DiscoveredConfig
from .xray import XrayManager
from .net import (
    resolve_ipv4,
    resolve_all_ips,
    resolve_all_ipv4,
    is_url_reachable,
    is_any_url_reachable,
    lookup_geo,
    http_probe_through_socks,
)
from .service import ServerService
from .connection_manager import ConnectionManager

__version__ = "3.0.0"
__all__ = [
    "ServerRecord",
    "Endpoint",
    "SourceDefinition",
    "DiscoveredConfig",
    "ServerService",
    "ConnectionManager",
    "XrayManager",
    "resolve_ipv4",
    "resolve_all_ips",
    "resolve_all_ipv4",
    "is_url_reachable",
    "is_any_url_reachable",
    "lookup_geo",
    "http_probe_through_socks",
]
