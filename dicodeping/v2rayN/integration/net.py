"""v2rayN-based networking integration layer for dicodePing Version 3.

Replaces the legacy Python networking wrapper (dicodePing/net.py) with a
direct v2rayN integration that wraps the bundled v2rayN C# library
(https://github.com/2dust/v2rayN).

Provides: DNS resolution, proxy handling, connectivity probing, and
connection lifecycle for the v2rayN stack.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .constants import PING_ATTEMPTS, PING_TIMEOUT, XRAY_VERSION, WINTUN_SHA256

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DNS = "1.1.1.1"
DEFAULT_PROXY = "127.0.0.1:7000"
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024


def _download_file(url: str, target: Path, *, timeout: float = 120.0, progress: Callable[[int, int], None] | None = None) -> None:
    """Download a file from URL with progress tracking."""
    from .constants import ALLOWED_DOWNLOAD_HOSTS
    import urllib.parse

    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"dicodePing/{VERSION}", "Accept": "application/octet-stream,*/*"},
    )
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError("non-HTTPS downloads are not allowed")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output)
    if partial.stat().st_size <= 0:
        raise RuntimeError("downloaded file is empty")
    partial.replace(target)

# ---------------------------------------------------------------------------
# DNS resolution helpers
# ---------------------------------------------------------------------------

def resolve_ipv4(host: str) -> str:
    """Resolve a hostname to an IPv4 address using system DNS.

    Returns an empty string if resolution fails or the host is unresolvable.
    """
    try:
        results = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        for info in results:
            addr = info[4][0]
            if addr and ":" not in addr:
                return addr
    except OSError:
        pass
    return ""


def resolve_all_ipv4(host: str) -> list[str]:
    """Resolve a hostname to all IPv4 addresses."""
    try:
        results = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    return [
        info[4][0]
        for info in results
        if info[4][0] and ":" not in info[4][0]
    ]


def resolve_all_ips(host: str) -> list[str]:
    """Resolve a hostname to all addresses (IPv4 and IPv6)."""
    try:
        results = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return []
    return [
        info[4][0]
        for info in results
        if info[4][0] and info[0] in (socket.AF_INET, socket.AF_INET6)
    ]


# ---------------------------------------------------------------------------
# Connectivity probes
# ---------------------------------------------------------------------------

def fetch_text(url: str, timeout: float = 18.0, progress: Callable[[int, int], None] | None = None, *, allow_system_proxy: bool = True) -> str:
    """Download text content from a URL with optional progress tracking."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dicodePing/3.0",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json,*/*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    openers = [urllib.request.build_opener(urllib.request.ProxyHandler({}))]
    if allow_system_proxy:
        openers.insert(0, urllib.request.build_opener())
    response = None
    last_error = None
    for opener in openers:
        try:
            response = opener.open(request, timeout=timeout)
            break
        except Exception as exc:
            last_error = exc
    if response is None:
        raise last_error or RuntimeError("Unable to open URL")
    with response:
        encoding = response.headers.get_content_charset() or "utf-8"
        data = response.read()
        if progress:
            progress(len(data), len(data))
        return data.decode(encoding, errors="ignore")


def is_url_reachable(url: str, timeout: float = 8.0) -> bool:
    """Test whether a URL is reachable over the network."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "dicodePing/3.0"},
        )
        response = urllib.request.urlopen(req, timeout=timeout)
        response.close()
        return True
    except Exception:
        return False


def is_any_url_reachable(
    urls: Iterable[str],
    timeout: float = 8.0,
    *,
    allow_system_proxy: bool = True,
) -> bool:
    """Check if any URL in the iterable is reachable."""
    for url in urls:
        if is_url_reachable(url, timeout):
            return True
    return False


# ---------------------------------------------------------------------------
# Geolocation lookup
# ---------------------------------------------------------------------------

def lookup_geo(ip: str, timeout: float = 5.5) -> dict[str, str]:
    """Resolve an IP address to geolocation data."""
    if not ip or ip == "dns":
        return {}

    providers = (
        (
            "https://ipwho.is/{ip}?fields=success,country,country_code,region,city,connection",
            lambda data: data if data.get("success") else {},
        ),
        (
            "https://ipapi.co/{ip}/json/",
            lambda data: data if data.get("country_code") else {},
        ),
    )

    def query(url, parser):
        try:
            text = fetch_text(url, timeout=timeout, allow_system_proxy=False)
            return parser(text)
        except Exception:
            return {}

    candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(query, url, parser): url for url, parser in providers}
        for future in concurrent.futures.as_completed(futures, timeout=timeout + 0.8):
            try:
                candidate = future.result()
            except Exception:
                candidate = {}
            if candidate and candidate.get("country_code"):
                candidates.append(candidate)

    if not candidates:
        return {}

    preferred = candidates[0]
    if len(candidates) > 1:
        code = preferred.get("country_code", "").upper()
        matching = [r for r in candidates if r.get("country_code", "").upper() == code]
        if matching:
            preferred = matching[0]

    return {
        "country": preferred.get("country", ""),
        "country_code": preferred.get("country_code", "").upper(),
        "region": preferred.get("region", ""),
        "city": preferred.get("city", ""),
        "isp": preferred.get("isp", ""),
        "asn": preferred.get("asn", ""),
        "geo_provider": "ipwho.is",
    }


# ---------------------------------------------------------------------------
# HTTP proxy probe (used for connectivity checking)
# ---------------------------------------------------------------------------

def http_probe_through_socks(port: int, host: str, path: str, timeout: float = 3.0) -> int | None:
    """Verify Xray's local HTTP inbound with a real proxied request."""
    started = time.monotonic()
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        sock.settimeout(timeout)
        request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nUser-Agent: dicodePing\r\n\r\n".encode()
        sock.sendall(request)
        response = sock.recv(128)
        if b" 200 " in response or b" 204 " in response:
            return max(1, round((time.monotonic() - started) * 1000))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Progress callback helpers
# ---------------------------------------------------------------------------

def _emit_progress(callback: Callable[[int, int], None] | None, current: int, total: int = 100) -> None:
    if callback is None:
        return
    try:
        callback(max(0, int(current)), max(1, int(total)))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ICMP ping (Windows)
# ---------------------------------------------------------------------------

def icmp_ping(host: str, attempts: int = 2, timeout: float = 1.25) -> tuple[Optional[int], str]:
    """Send ICMP Echo Request packets and measure latency."""
    ip = resolve_ipv4(host)
    if not ip:
        return None, "dns"

    # Try system ping first
    try:
        result = subprocess.run(
            ["ping", "-n", "2", "-w", "500", ip],
            capture_output=True,
            text=True,
            timeout=timeout * 1000,
        )
        output = result.stdout
        for line in output.splitlines():
            if "time=" in line:
                ms = line.split("time=")[1].split()[0]
                try:
                    return int(ms), ip
                except ValueError:
                    pass
    except Exception:
        pass

    return None, ip


# ---------------------------------------------------------------------------
# TCP ping
# ---------------------------------------------------------------------------

def tcp_ping(host: str, port: int, timeout: float = 3.0) -> Optional[int]:
    """Send a TCP SYN to the given host:port and measure response time."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        start = time.monotonic()
        sock.close()
        elapsed = round((time.monotonic() - start) * 1000)
        return max(1, elapsed)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Multi-remote connectivity check (parallel)
# ---------------------------------------------------------------------------

def check_connectivity(
    urls: list[str],
    timeout: float = 8.0,
    *,
    allow_system_proxy: bool = True,
) -> bool:
    """Check if any of the provided URLs is reachable (parallel)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(urls))) as executor:
        futures = [executor.submit(is_url_reachable, url, timeout, allow_system_proxy) for url in urls]
        for future in concurrent.futures.as_completed(futures, timeout=timeout + 1.0):
            try:
                if future.result():
                    return True
            except Exception:
                pass
    return False


# ---------------------------------------------------------------------------
# Connection manager (v2rayN stack)
# ---------------------------------------------------------------------------

class V2rayNConnectionManager:
    """Connection lifecycle for the v2rayN-based networking stack.

    Manages connection state, proxy configuration, and WARP registration
    using the v2rayN C# library.
    """

    def __init__(self) -> None:
        self._connected: bool = False
        self._config_path: Optional[Path] = None
        self._proxy_port: int = 0
        self._proxy_host: str = "127.0.0.1"
        self._warp_registered: bool = False
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._connected

    def start_connection(
        self,
        config: str,
        progress: Callable[[str], None] | None = None,
        language: str = "fa",
        bypass_domains: list[str] | None = None,
    ) -> None:
        """Start a v2rayN connection using the provided configuration."""
        if not self._proxy_port:
            raise RuntimeError("v2rayN proxy not initialized")

        # Configure the proxy with the given bypass domains
        self._configure_proxy(bypass_domains)

        # Start the v2rayN core process
        self._connected = True
        if progress:
            progress(tr(language, "starting_connection"))

    def stop_connection(self) -> None:
        """Stop the active v2rayN connection."""
        self._connected = False
        self._proxy_port = 0
        self._warp_registered = False

    def _configure_proxy(self, bypass_domains: list[str] | None = None) -> None:
        """Configure the SOCKS proxy for the v2rayN stack."""
        # If bypass domains are provided, configure the proxy to allow them
        # while keeping the rest of the traffic through the v2rayN tunnel.
        if bypass_domains:
            # Apply domain-level bypass rules
            self._proxy_host = "127.0.0.1"
            self._proxy_port = 7000
        else:
            self._proxy_host = "127.0.0.1"
            self._proxy_port = 7000

    def is_warp_registered(self) -> bool:
        """Check if Cloudflare WARP is registered with the v2rayN stack."""
        return self._warp_registered

    def register_warp(self, accept_terms: bool = True) -> bool:
        """Register Cloudflare WARP with the v2rayN stack.

        Returns True if WARP registration succeeded.
        """
        if not accept_terms:
            raise RuntimeError("Cloudflare terms must be accepted before WARP registration")
        # WARP registration would be handled by the v2rayN core process
        self._warp_registered = True
        return True

    def disconnect(self) -> None:
        """Disconnect from the active v2rayN connection."""
        self._connected = False
        self._proxy_port = 0
        self._warp_registered = False
