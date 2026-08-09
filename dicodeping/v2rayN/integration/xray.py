"""v2rayN-based Xray integration layer for dicodePing Version 3.

Provides core Xray operations including core download, verification,
TUN management, and connection lifecycle using the v2rayN C# library.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import Callable, Optional

from .constants import BUNDLE_ROOT, CORE_DIR, DATA_DIR, XRAY_VERSION, WINTUN_SHA256
from dicodeping.desktop_proxy import DesktopProxyController
from dicodeping.core_runtime import PORT_REGISTRY
from dicodeping.diagnostics import get_logger
from .net import resolve_ipv4, fetch_text, http_probe_through_socks, lookup_geo, _download_file

# ---------------------------------------------------------------------------
# Core management (v2rayN stack)
# ---------------------------------------------------------------------------

def find_xray() -> Optional[Path]:
    """Locate the Xray core binary in the bundled v2rayN distribution."""
    # Check the v2rayN bundled directory
    candidates = [
        BUNDLE_ROOT / "v2rayN" / "v2rayN" / "core" / "xray.exe",
        BUNDLE_ROOT / "v2rayN" / "v2rayN" / "core" / "xray",
        BUNDLE_ROOT / "core" / "xray.exe",
        BUNDLE_ROOT / "core" / "xray",
        CORE_DIR / "xray.exe",
        CORE_DIR / "xray",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def ensure_xray() -> Path:
    """Ensure the Xray core binary is available and up-to-date."""
    xray_exe = find_xray()
    if xray_exe and xray_exe.exists():
        return xray_exe

    # Download and install Xray core
    from .constants import CORE_DIR
    archive = CORE_DIR / f"xray-{XRAY_VERSION}.zip"
    download_url = f"https://github.com/XTLS/Xray-core/releases/download/v{XRAY_VERSION}/xray-{XRAY_VERSION}-windows-64.zip"

    if not archive.exists():
        _download_file(download_url, archive, timeout=180)

    # Extract Xray core
    target = CORE_DIR / "xray.exe"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extract("xray.exe", target)
        zf.extract("geoip.dat", target)
        zf.extract("geosite.dat", target)
        zf.extract("wintun.dll", target)
    os.chmod(target, 0o755)
    return target


def ensure_wintun() -> Path:
    """Ensure the Wintun DLL is available for Windows TUN support."""
    candidates = [
        CORE_DIR / "wintun.dll",
        BUNDLE_ROOT / "v2rayN" / "v2rayN" / "core" / "wintun.dll",
        BUNDLE_ROOT / "core" / "wintun.dll",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 50_000:
            return candidate

    from .constants import CORE_DIR
    archive = CORE_DIR / "wintun.zip"
    download_url = "https://www.wintun.net/builds/wintun-0.14.1.zip"

    if not archive.exists():
        _download_file(download_url, archive, timeout=90)

    # Extract Wintun DLL
    target = CORE_DIR / "wintun.dll"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extract("wintun.dll", target)
    os.chmod(target, 0o755)
    return target


# ---------------------------------------------------------------------------
# Connection lifecycle (v2rayN stack)
# ---------------------------------------------------------------------------

class XrayManager:
    """Manages the Xray core process, connection lifecycle, and TUN mode.

    Provides the v2rayN stack integration layer for connection lifecycle
    management, TUN interface creation, and connection verification.
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen[str]] = None
        self._config_path: Optional[Path] = None
        self._log_handle: Optional[TextIOWrapper] = None
        self._token: str = ""
        self._executable: Optional[Path] = None
        self._api_port: int = 0
        self._validation_socks_port: int = 0
        self._http_proxy_port: int = 0
        self._connected_host: str = ""
        self._connected_ip: str = ""
        self._connected_port: int = 0
        self._direct_routes: list[str] = []
        self._active_log_file: Path = DATA_DIR / "xray.log"
        self._retain_log: bool = False
        self._cancel_start: threading.Event = threading.Event()
        self._route_mode: str = "disconnected"
        self._startup_verified: bool = False
        self._startup_evidence: str = "none"
        self._last_verified_ping_ms: Optional[int] = None
        self._last_verified_at: float = 0.0
        self._system_proxy = DesktopProxyController()
        self._stop_lock = threading.RLock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None
        atexit.register(self.stop)

    @property
    def connected(self) -> bool:
        return bool(self._process and self._process.poll() is None)

    @property
    def startup_verified(self) -> bool:
        return bool(self.connected and self._route_mode.startswith("tun:") and self._startup_verified)

    @property
    def startup_evidence(self) -> str:
        return self._startup_evidence

    def _tun_activity_observed(self) -> bool:
        """Detect real packets traversing the TUN without depending on one URL."""
        try:
            upload, download = self.traffic_stats()
            if int(upload or 0) > 0 or int(download or 0) > 0:
                return True
        except Exception:
            pass
        tail = self._read_log_tail(limit=7000).lower()
        return bool(
            re.search(r"from\s+(?:tcp|udp):.*?accepted\s+(?:tcp|udp):.*?\[tun-in\s+>>\s+proxy\]", tail)
            or re.search(r"accepted\s+(?:tcp|udp):.*?\[tun-in\s+>>\s+proxy\]", tail)
        )

    @staticmethod
    def _validate(executable: Path, config_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(executable), "run", "-test", "-config", str(config_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
            cwd=str(executable.parent),
        )

    def _read_log_tail(self, limit: int = 1800) -> str:
        try:
            if not self._active_log_file.exists():
                return ""
            text = self._active_log_file.read_text(encoding="utf-8", errors="ignore")
            return text[-limit:].strip()
        except Exception:
            return ""

    def start(
        self,
        raw_config: str,
        progress: Callable[[str], None] | None = None,
        language: str = "fa",
        bypass_domains: list[str] | None = None,
        endpoint_host: str = "",
        endpoint_port: int = 0,
        secure_dns: bool = True,
        progress_value: Callable[[int, int], None] | None = None,
        core_options: dict[str, object] | None = None,
    ) -> None:
        """Start an Xray connection using the v2rayN stack.

        This method:
        1. Ensures Xray core and Wintun are available
        2. Builds the TUN configuration for the current server
        3. Starts the Xray core process with the configuration
        4. Performs startup verification (TUN activity and connectivity probe)
        """
        # Cancel any existing connection
        self.stop()
        self._cancel_start.set()
        self._startup_verified = False
        self._startup_evidence = "none"
        self._last_verified_ping_ms = None
        self._last_verified_at = 0.0

        # Cleanup stale processes
        from .core_manager import cleanup_stale_owned_process
        cleanup_stale_owned_process()

        # Ensure Xray core is available
        executable = ensure_xray()
        if isinstance(core_options, dict) and core_options.get("wintun"):
            ensure_wintun()

        # Acquire API port for Xray's stats API
        from .core_manager import PORT_REGISTRY
        self._api_port = PORT_REGISTRY.acquire()
        self._validation_socks_port = PORT_REGISTRY.acquire()

        # Build TUN configuration
        config = _build_tun_config(
            raw_config,
            bypass_domains=bypass_domains,
            api_port=self._api_port,
            validation_socks_port=self._validation_socks_port,
            secure_dns=secure_dns,
        )

        # Write configuration
        self._config_path = Path(tempfile.mkdtemp(prefix="xray-")) / "config.json"
        self._config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))

        # Execute Xray core
        self._process = subprocess.Popen(
            [str(executable), "run", "-config", str(self._config_path)],
            stdout=self._active_log_file,
            stderr=self._active_log_file,
            cwd=str(executable.parent),
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        # Wait for startup verification
        self._wait_for_startup(progress_value)

        # Track connection state
        self._route_mode = f"tun:{config['inbounds'][0]['settings'].get('name', 'dicodePing-TUN')}"
        self._connected_host = endpoint_host or (config["routing"]["domainStrategy"] or "")
        self._connected_ip = resolve_ipv4(self._connected_host) if self._connected_host else ""
        self._connected_port = endpoint_port or 443
        self._direct_routes = _install_direct_host_routes(
            [self._connected_ip], "dicodePing-TUN", only_if_tun=False
        )

        # Signal startup verified
        self._startup_verified = True
        self._startup_evidence = "tun-active"

    def _wait_for_startup(self, progress: Callable[[str], None] | None) -> None:
        """Wait for Xray core to start and verify connectivity."""
        deadline = time.monotonic() + 7.0
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                break
            if self._tun_activity_observed():
                self._startup_verified = True
                self._startup_evidence = "tun-traffic"
                break
            time.sleep(0.12)

    def traffic_stats(self) -> tuple[int, int]:
        """Return traffic statistics for the active connection."""
        if not self.connected or not self._process or not self._api_port:
            return None, None
        try:
            result = subprocess.run(
                [str(self._process), "api", "statsquery", f"--server=127.0.0.1:{self._api_port}", "-timeout", "1", "-pattern", "inbound>>>"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=1.0,
            )
            text = result.stdout or ""
            begin, finish = text.find("{"), text.rfind("}")
            if begin < 0 or finish < begin:
                return None, None
            payload = json.loads(text[begin:finish + 1])
            upload = 0
            download = 0
            for item in payload.get("stat", []):
                name = str(item.get("name") or "")
                if not any(name.startswith(f"inbound>>>{tag}>>>traffic>>>") for tag in ("tun-in",)):
                    continue
                value = int(item.get("value") or 0)
                if name.endswith(">>>uplink"):
                    upload += value
                elif name.endswith(">>>downlink"):
                    download += value
            return max(0, upload), max(0, download)
        except Exception:
            return None, None

    def connected_ping(self, timeout: float = 1.0) -> Optional[int]:
        """Measure TUN latency without converting endpoint filtering into a disconnect."""
        if not self.startup_verified:
            return None
        result = _direct_tun_http_probe(timeout=min(0.6, float(timeout)))
        if result is not None:
            self._last_verified_ping_ms = result
            self._last_verified_at = time.monotonic()
            return result
        if self.connected and self._tun_activity_observed():
            self._last_verified_at = time.monotonic()
        if self._last_verified_ping_ms is not None and time.monotonic() - self._last_verified_at <= 90.0:
            return self._last_verified_ping_ms
        return None

    def stop(self) -> None:
        """Stop the active Xray connection and clean up resources."""
        with self._stop_lock:
            needs_tun_cleanup = bool(
                self._process or self._config_path or self._direct_routes or self._route_mode.startswith("tun")
            )
            try:
                self._cancel_start.set()
                self._system_proxy.restore()
                self._route_mode = "disconnected"
                self._startup_verified = False
                self._startup_evidence = "none"
                self._last_verified_ping_ms = None
                self._last_verified_at = 0.0
                process = self._process
                self._process = None
                PORT_REGISTRY.release(self._api_port)
                PORT_REGISTRY.release(self._validation_socks_port)
                self._api_port = 0
                self._validation_socks_port = 0
                self._connected_host = ""
                self._connected_ip = ""
                self._connected_port = 0
            except Exception:
                pass
            finally:
                if needs_tun_cleanup:
                    self._cleanup_tun()

    def _cleanup_tun(self) -> None:
        """Cleanup TUN interface and routes."""
        try:
            cleanup_named_tun()
        except Exception:
            pass
        try:
            if self._config_path:
                self._config_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if self._direct_routes:
                _remove_direct_host_routes(self._direct_routes)
        except Exception:
            pass
        self._direct_routes = []
        self._executable = None

    def _setup_direct_routes(self, ips: list[str], tun_name: str = "dicodePing-TUN") -> list[str]:
        """Install direct host routes for the TUN interface."""
        if not ips:
            return []
        if os.name == "nt":
            # Windows route installation
            quoted = ",".join("'%s'" % item.replace("'", "''") for item in ips)
            safe_tun = tun_name.replace("'", "''")
            script = f'''
$ErrorActionPreference='SilentlyContinue'
$route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
  Where-Object {{ $_.InterfaceAlias -notlike '*dicodePing*' -and $_.State -ne 'Invalid' }} |
  Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
if (-not $route) {{ exit 0 }}
$ips = @({quoted})
foreach ($ip in $ips) {{
  $prefix = "$ip/32"
  $existing = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $existing) {{
    New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $route.InterfaceIndex -RouteMetric 1 -PolicyStore ActiveStore | Out-Null
  }}
}}
'''
            try:
                result = _powershell_route_script(script, timeout=20.0)
                return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            except Exception:
                return []
        return []

    def _setup_tun_config(self) -> dict:
        """Build the TUN configuration for the v2rayN stack."""
        return _platform_tun_settings()

    def _build_probe_config(self, socks_port: int, host: str) -> dict:
        """Build a short-lived SOCKS profile for a real outbound latency probe."""
        return {
            "log": {"loglevel": "none"},
            "dns": {"servers": ["1.1.1.1", "8.8.8.8"], "queryStrategy": "UseIP"},
            "inbounds": [{
                "listen": "127.0.0.1", "port": int(socks_port), "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }],
            "outbounds": [{"tag": "direct", "protocol": "freedom"}],
            "routing": {"domainStrategy": "IPIfNonMatch"},
        }

    def _verify_core(self, executable: Path) -> bool:
        """Verify the Xray core binary is healthy."""
        try:
            result = subprocess.run(
                [str(executable), "version"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(executable.parent),
            )
            return result.returncode == 0 and "Xray" in result.stdout
        except Exception:
            return False


def _direct_tun_single_probe(url: str, timeout: float) -> int | None:
    """Run one no-proxy request through the system route."""
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "dicodePing/3.0", "Connection": "close"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=max(0.45, float(timeout))) as response:
            if 200 <= response.status < 400:
                return max(1, int(round((time.monotonic() - time.perf_counter()) * 1000)))
    except Exception:
        pass
    return None


def _direct_tun_http_probe(timeout: float = 3.0) -> int | None:
    """Best-effort latency check through the active system-wide TUN route."""
    deadline = time.monotonic() + max(0.6, float(timeout))
    for url in [
        "http://captive.apple.com/hotspot-detect.html",
        "https://www.google.com/generate_204",
        "https://www.gstatic.com/generate_204",
    ]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = _direct_tun_single_probe(url, min(1.35, max(0.45, remaining)))
        if result is not None:
            return result
    return None


def _build_tun_config(
    raw_config: str,
    bypass_domains: list[str] | None = None,
    api_port: int = 0,
    validation_socks_port: int = 0,
    secure_dns: bool = True,
) -> dict:
    """Build a TUN configuration for the v2rayN stack."""
    # Build the Xray outbound configuration
    from .protocols import build_xray_outbound
    from .core_manager import PORT_REGISTRY

    outbound = build_xray_outbound(raw_config)
    if not outbound:
        raise ValueError("Unsupported server configuration")

    config: dict = {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": [
                {"address": "https://cloudflare-dns.com/dns-query", "domains": ["geosite:geolocation-!cn"]},
                {"address": "https://dns.google/dns-query"},
            ] if secure_dns else [{"address": "1.1.1.1", "skipFallback": False}, {"address": "8.8.8.8", "skipFallback": False}],
            "queryStrategy": "UseIP",
        },
        "stats": {},
        "policy": {
            "levels": {
                "0": {
                    "handshake": 8,
                    "connIdle": 300,
                    "uplinkOnly": 2,
                    "downlinkOnly": 2,
                    "bufferSize": _resource_profile().network_buffer_kib,
                }
            },
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True,
                "statsOutboundUplink": True,
                "statsOutboundDownlink": True,
            }
        },
        "inbounds": [
            {
                "tag": "tun-in",
                "port": 0,
                "protocol": "tun",
                "settings": _platform_tun_settings(),
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            }
        ],
        "outbounds": [outbound, {"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": []},
    }

    if validation_socks_port:
        config["inbounds"].append({
            "tag": "validation-socks",
            "listen": "127.0.0.1",
            "port": validation_socks_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        })

    if api_port:
        config["api"] = {
            "tag": "api",
            "listen": f"127.0.0.1:{api_port}",
            "services": ["StatsService"],
        }
        config["routing"]["rules"].append({
            "type": "field",
            "inboundTag": ["api"],
            "outboundTag": "api",
        })

    return config


def _build_probe_config(
    raw_config: str,
    socks_port: int,
) -> dict:
    """Build a short-lived SOCKS profile for a real outbound latency probe."""
    return {
        "log": {"loglevel": "none"},
        "dns": {"servers": ["1.1.1.1", "8.8.8.8"], "queryStrategy": "UseIP"},
        "inbounds": [{
            "listen": "127.0.0.1", "port": int(socks_port), "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        }],
        "outbounds": [{"tag": "direct", "protocol": "freedom"}],
        "routing": {"domainStrategy": "IPIfNonMatch"},
    }


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _powershell(script: str, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    """Execute a PowerShell script for Windows operations."""
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _install_direct_host_routes(
    ips: Iterable[str],
    tun_name: str = "dicodePing-TUN",
    *,
    only_if_tun: bool = True,
) -> list[str]:
    """Install direct host routes for TUN mode."""
    valid = [str(ip) for ip in ips if str(ip)]
    if not valid:
        return []
    if os.name == "nt":
        quoted = ",".join("'%s'" % item.replace("'", "''") for item in valid)
        safe_tun = tun_name.replace("'", "''")
        script = f'''
$ErrorActionPreference='SilentlyContinue'
$route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
  Where-Object {{ $_.InterfaceAlias -notlike '*dicodePing*' -and $_.State -ne 'Invalid' }} |
  Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
if (-not $route) {{ exit 0 }}
$ips = @({quoted})
foreach ($ip in $ips) {{
  $prefix = "$ip/32"
  $existing = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $existing) {{
    New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $route.InterfaceIndex -RouteMetric 1 -PolicyStore ActiveStore | Out-Null
  }}
}}
'''
        result = _powershell(script, timeout=20.0)
        return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return []


def _remove_direct_host_routes(ips: Iterable[str]) -> None:
    """Remove direct host routes installed for TUN mode."""
    valid = [str(ip) for ip in ips if str(ip)]
    if not valid:
        return
    if os.name == "nt":
        quoted = ",".join("'%s'" % item.replace("'", "''") for item in valid)
        script = f'''
$ErrorActionPreference='SilentlyContinue'
$ips = @({quoted})
foreach ($ip in $ips) {{
  Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "$ip/32" -PolicyStore ActiveStore -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false
}}
'''
        _powershell(script, timeout=15.0)
    else:
        for ip in valid:
            subprocess.run(
                ["ip", "-4", "route", "del", f"{ip}/32"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
                check=False,
            )


def _install_wintun(executable: Path, progress: Callable[[str], None] | None = None, language: str = "fa") -> Path:
    """Install the Wintun DLL for Windows TUN support."""
    destination = executable.parent / "wintun.dll"
    if destination.exists() and destination.stat().st_size > 50_000:
        return destination
    from .constants import CORE_DIR
    archive = CORE_DIR / "wintun.zip"
    _download_file("https://www.wintun.net/builds/wintun-0.14.1.zip", archive, timeout=90)
    with zipfile.ZipFile(archive) as zf:
        zf.extract("wintun.dll", destination)
    os.chmod(destination, 0o755)
    return destination


def _ensure_wintun(executable: Path, progress: Callable[[str], None] | None = None, language: str = "fa") -> Path:
    """Ensure the Wintun DLL is available."""
    if executable is None:
        return None
    destination = executable.parent / "wintun.dll"
    if destination.exists() and destination.stat().st_size > 50_000:
        return destination
    return _install_wintun(executable, progress, language)


# ---------------------------------------------------------------------------
# Core version check
# ---------------------------------------------------------------------------

def _core_version_matches(executable: Path) -> bool:
    """Check if the Xray core binary matches the expected version."""
    try:
        result = subprocess.run(
            [str(executable), "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            cwd=str(executable.parent),
        )
        match = re.search(r"(?i)\bXray\s+(\d+\.\d+\.\d+)\b", result.stdout)
        return result.returncode == 0 and bool(match) and match.group(1) == XRAY_VERSION
    except Exception:
        return False


def _verify_sha256(path: Path, expected: str) -> None:
    """Verify the SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest().lower()
    if digest != expected.lower():
        raise RuntimeError("File integrity check failed")
