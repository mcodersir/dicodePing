"""v2rayN-based discovery layer for dicodePing Version 3.

Handles subscription fetching, parsing, and server discovery
using the v2rayN stack integration.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .constants import DEFAULT_SUBSCRIPTION_URL, DEFAULT_SUBSCRIPTION_FALLBACK, DEFAULT_SUBSCRIPTION_MIRRORS
from .models import ServerRecord, SourceDefinition, DiscoveredConfig, utc_now
from .net import fetch_text, is_url_reachable
from .protocols import parse_endpoint, record_id
from dicodeping.diagnostics import get_logger
from dicodeping.storage import JsonStore

LOGGER = get_logger("discovery")


def _fetch_subscription(source_url: str) -> str:
    """Download a subscription file from a URL."""
    if not is_url_reachable(source_url, timeout=18):
        raise RuntimeError(f"subscription source is unreachable: {source_url}")
    try:
        response = urllib.request.urlopen(source_url, timeout=18)
        return response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"failed to download subscription from {source_url}: {exc}")


def _parse_subscription(text: str) -> Iterable[str]:
    """Parse a subscription text and yield individual server configurations."""
    text = text.strip()
    if not text:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def _get_servers_from_raw(text: str) -> list[str]:
    """Extract server configurations from raw subscription text."""
    configs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" in line[:1000]:
            configs.append(line)
    return configs


def discover_servers(
    source_url: str = DEFAULT_SUBSCRIPTION_URL,
    source_name: str = "default",
    language: str = "fa",
    *,
    skip_fetch: bool = False,
) -> list[DiscoveredConfig]:
    """Discover servers from a subscription source.

    Returns a list of discovered configurations with server details.
    """
    if not skip_fetch:
        try:
            text = fetch_text(source_url, timeout=30, allow_system_proxy=True)
        except Exception as exc:
            LOGGER.warning("Failed to fetch subscription: %s", exc)
            text = ""
    else:
        text = ""

    if not text:
        text = _fetch_subscription(source_url)

    configs = []
    for raw in _get_servers_from_raw(text):
        endpoint = parse_endpoint(raw)
        if not endpoint:
            continue
        config = DiscoveredConfig(raw, source_id="default", source_name=source_name, source_order=0)
        configs.append(config)
    return configs


def _extract_server_configs(text: str) -> list[str]:
    """Extract server configurations from subscription text."""
    return _get_servers_from_raw(text)


def _parse_server_info(text: str) -> list[ServerRecord]:
    """Parse server info from a subscription text."""
    configs = []
    for raw in _extract_server_configs(text):
        endpoint = parse_endpoint(raw)
        if not endpoint:
            continue
        server_id = record_id(raw)
        configs.append(ServerRecord(
            id=server_id,
            name="Server",
            protocol=endpoint.protocol.upper(),
            host=endpoint.host,
            port=endpoint.port,
            config_blob="",
            ping_ms=None,
            ip="",
            country="",
            country_code="",
            region="",
            city="",
            isp="",
            asn="",
            geo_provider="",
            geo_confidence="",
            source_id="default",
            source_name=source_name,
            source_order=0,
            status="unverified",
            favorite=False,
            last_checked="",
            last_connected="",
            failures=0,
            profile_tag="unknown",
            security_score=0,
            security_level="unknown",
            security_summary="",
        ))
    return configs


def _get_discoverable_servers(
    source_url: str = DEFAULT_SUBSCRIPTION_URL,
    language: str = "fa",
) -> list[ServerRecord]:
    """Get discoverable servers from the subscription source."""
    try:
        text = fetch_text(source_url, timeout=30, allow_system_proxy=True)
    except Exception:
        text = ""
    return _parse_server_info(text)


def resolve_server(source_url: str = DEFAULT_SUBSCRIPTION_URL, language: str = "fa") -> list[ServerRecord]:
    """Resolve servers from a subscription source."""
    return _parse_server_info(fetch_text(source_url, timeout=30, allow_system_proxy=True))
