from __future__ import annotations

import atexit
import ctypes
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable

from .constants import (
    APP_NAME,
    APP_ROOT,
    BUNDLED_CORE_DIR,
    CORE_DIR,
    LOG_FILE,
    PID_FILE,
    RUNTIME_DIR,
    VERSION,
    WINTUN_SHA256,
    WINTUN_URL,
    XRAY_RELEASE_BASE,
    XRAY_VERSION,
)
from .diagnostics import diagnostics_enabled, get_logger
from .i18n import tr
from .net import install_direct_host_routes, remove_direct_host_routes, resolve_all_ips
from .protocols import build_xray_outbound, parse_endpoint
from .resource_tuning import current_resource_profile
from .core_runtime import PORT_REGISTRY, PROCESS_REGISTRY
from .desktop_proxy import DesktopProxyController, restore_stale_system_proxy

TUN_NAME = "dicodePing-TUN"
LOGGER = get_logger("connection")
_PROBE_CORE_LOCK = threading.Lock()


def normalize_bypass_domains(values: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if values is None:
        return []
    rows = values.replace(",", "\n").splitlines() if isinstance(values, str) else list(values)
    result: list[str] = []
    for raw in rows:
        value = str(raw or "").strip().lower()
        if not value or value.startswith("#"):
            continue
        value = value.removeprefix("domain:").removeprefix("full:")
        value = value.removeprefix("http://").removeprefix("https://")
        value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        value = value.split(":", 1)[0].strip(".*. ")
        if value.startswith("www."):
            value = value[4:]
        try:
            value = value.encode("idna").decode("ascii")
        except Exception:
            continue
        if not value or "." not in value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-." for ch in value):
            continue
        if value not in result:
            result.append(value)
    return result[:256]


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def is_admin() -> bool:
    if not is_windows():
        return os.geteuid() == 0 if hasattr(os, "geteuid") else True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relaunch the desktop application with the privileges required by TUN.

    Windows uses the normal UAC prompt, Linux uses PolicyKit, and macOS uses
    the system administrator-password dialog.  User data/session environment
    is preserved so an elevated launch does not create a second empty profile.
    """
    if is_admin():
        return False
    system = platform.system().lower()
    if is_windows():
        executable = sys.executable
        if getattr(sys, "frozen", False):
            parameters = subprocess.list2cmdline(sys.argv[1:])
        else:
            parameters = subprocess.list2cmdline([str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters, str(APP_ROOT), 1)
        return int(result) > 32

    command = [sys.executable, *sys.argv[1:]] if getattr(sys, "frozen", False) else [
        sys.executable,
        str(Path(sys.argv[0]).resolve()),
        *sys.argv[1:],
    ]
    preserved_names = (
        "HOME", "USER", "LOGNAME", "PATH", "TMPDIR",
        "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
        "DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
        "QT_QPA_PLATFORM", "QT_SCALE_FACTOR", "QT_AUTO_SCREEN_SCALE_FACTOR",
    )
    environment = [f"{name}={os.environ[name]}" for name in preserved_names if os.environ.get(name)]

    if system == "darwin":
        osascript = shutil.which("osascript")
        if not osascript:
            return False
        shell_command = shlex.join(["env", *environment, *command])
        escaped = shell_command.replace("\\", "\\\\").replace('"', '\\"')
        script = f'do shell script "{escaped}" with administrator privileges'
        try:
            subprocess.Popen(
                [osascript, "-e", script],
                cwd=str(APP_ROOT),
                start_new_session=True,
            )
            return True
        except OSError:
            return False

    # Linux TUN creation needs CAP_NET_ADMIN. PolicyKit keeps the prompt in
    # the user's graphical session while the preserved HOME keeps one profile.
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return False
    try:
        subprocess.Popen([pkexec, "env", *environment, *command], start_new_session=True)
        return True
    except OSError:
        return False


def _emit_progress_value(callback: Callable[[int, int], None] | None, current: int, total: int = 100) -> None:
    if callback is None:
        return
    try:
        callback(max(0, int(current)), max(1, int(total)))
    except Exception:
        LOGGER.debug("Progress callback failed", exc_info=True)


def _creation_flags() -> int:
    if not is_windows():
        return 0
    return subprocess.CREATE_NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _powershell(script: str, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        creationflags=_creation_flags(),
    )


def cleanup_named_tun() -> None:
    if not is_windows() or not is_admin():
        return
    script = """
$ErrorActionPreference='SilentlyContinue'
$adapters = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
  $_.Name -like '*dicodePing*' -or $_.InterfaceDescription -like '*dicodePing*'
}
foreach ($adapter in $adapters) {
  Get-NetRoute -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false
  Get-NetIPInterface -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue | Set-NetIPInterface -Dhcp Disabled
}
ipconfig /flushdns | Out-Null
"""
    try:
        _powershell(script, timeout=15)
    except Exception:
        # PowerShell may be busy, missing, or refusing to spawn during the
        # final stages of process teardown.  Never propagate the failure: the
        # caller (XrayManager.stop) is on the GUI thread and any exception
        # here would crash the app on Disconnect.
        LOGGER.debug("TUN cleanup PowerShell invocation failed", exc_info=True)


def _command_line_for_pid(pid: int) -> str:
    if not is_windows():
        try:
            return Path(f"/proc/{pid}/cmdline").read_text(errors="ignore").replace("\x00", " ")
        except Exception:
            return ""
    try:
        result = _powershell(
            f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CommandLine",
            timeout=8,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _kill_pid_tree(pid: int) -> None:
    if pid <= 0:
        return
    try:
        if is_windows():
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                creationflags=_creation_flags(),
            )
        else:
            group = os.getpgid(pid)
            if group == pid:
                os.killpg(group, 15)
            else:
                os.kill(pid, 15)
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                if group == pid:
                    os.killpg(group, 9)
                else:
                    os.kill(pid, 9)
    except Exception:
        pass


def cleanup_stale_owned_process() -> None:
    # A crash can leave the desktop pointed at a dead localhost proxy. Restore
    # the exact pre-connection settings before cleaning stale Xray processes.
    restore_stale_system_proxy()
    try:
        if not PID_FILE.exists():
            cleanup_named_tun()
            return
        info = json.loads(PID_FILE.read_text(encoding="utf-8"))
        pid = int(info.get("pid") or 0)
        config_path = str(info.get("config_path") or "")
        direct_routes = [str(value) for value in (info.get("direct_routes") or []) if value]
        command = _command_line_for_pid(pid)
        owned = bool(command and "xray" in command.lower() and config_path and config_path.lower() in command.lower())
        if owned:
            _kill_pid_tree(pid)
            time.sleep(0.4)
        remove_direct_host_routes(direct_routes)
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    cleanup_named_tun()


def _asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system.startswith("win"):
        return "Xray-windows-64.zip" if "64" in machine or machine in {"amd64", "x86_64"} else "Xray-windows-32.zip"
    if system.startswith("linux"):
        if machine in {"aarch64", "arm64"}:
            return "Xray-linux-arm64-v8a.zip"
        return "Xray-linux-64.zip"
    if system.startswith("darwin"):
        return "Xray-macos-arm64-v8a.zip" if machine in {"aarch64", "arm64"} else "Xray-macos-64.zip"
    return "Xray-windows-64.zip"


def _download_file(url: str, target: Path, timeout: float = 90.0) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME}/{VERSION}",
            "Accept": "application/octet-stream,*/*",
            "Cache-Control": "no-cache",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        if partial.stat().st_size <= 0:
            raise RuntimeError("فایل اتصال دریافت‌شده معتبر نیست")
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _pinned_asset_url() -> tuple[str, str]:
    name = _asset_name()
    return name, f"{XRAY_RELEASE_BASE}/{name}"


_XRAY_ARCHIVE_SHA256 = {
    "Xray-windows-64.zip": "af801b62c4d41d248d3db8016d4c6e2a7ccfb7ed443e3738aeb6f9e062321512",
    "Xray-linux-64.zip": "aa11c3685c71da0ffc71e511db50404609e7e963bb914b048f59a6a00af8930e",
    "Xray-macos-arm64-v8a.zip": "61f8f74d099098af710fa43613d9934d97b901dee909801d34f496cd463956d1",
    "Xray-macos-64.zip": "d8c116756d3a88a38a833a94bdf8bc801f69243ee888befcb56df8b4f1ec4878",
}


def _parse_sha256_digest(text: str) -> str:
    """Extract the SHA-256 value from Xray's companion .dgst asset."""
    preferred = re.search(
        r"(?im)^\s*(?:sha2?-?256|sha256)\s*[:=]\s*([a-f0-9]{64})\s*$",
        text,
    )
    if preferred:
        return preferred.group(1).lower()

    # Upstream digest formats have changed over time. A standalone 64-hex
    # token is unambiguously a SHA-256 digest even when its label is omitted.
    candidates = re.findall(r"(?i)(?<![a-f0-9])([a-f0-9]{64})(?![a-f0-9])", text)
    if len(candidates) == 1:
        return candidates[0].lower()
    raise RuntimeError("اعتبار بسته اتصال تأیید نشد")


def _extract_core(archive: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    executable_name = "xray.exe" if is_windows() else "xray"
    wanted = (executable_name, "geoip.dat", "geosite.dat", "wintun.dll")
    with zipfile.ZipFile(archive, "r") as package:
        names = package.namelist()
        for output_name in wanted:
            source_name = next((name for name in names if Path(name).name.lower() == output_name.lower()), None)
            if not source_name:
                continue
            with package.open(source_name) as source, (target_dir / output_name).open("wb") as output:
                shutil.copyfileobj(source, output)
    executable = target_dir / executable_name
    if not executable.exists():
        raise RuntimeError("بسته اتصال ناقص است")
    try:
        executable.chmod(0o755)
    except Exception:
        pass
    return executable


def _copy_bundled_core_to_user_dir() -> None:
    if not BUNDLED_CORE_DIR.exists() or BUNDLED_CORE_DIR.resolve() == CORE_DIR.resolve():
        return
    for name in ("xray.exe", "xray", "geoip.dat", "geosite.dat", "wintun.dll"):
        source = BUNDLED_CORE_DIR / name
        destination = CORE_DIR / name
        if not source.exists():
            continue
        # Always refresh Wintun from the executable bundle. A previous build may
        # have left a missing, truncated, or wrong-architecture DLL in AppData.
        must_copy = name in {"xray.exe", "xray", "wintun.dll"} or not destination.exists() or destination.stat().st_size != source.stat().st_size
        if must_copy:
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if name in {"xray", "xray.exe"} and not is_windows():
                    destination.chmod(0o755)
            except Exception:
                pass


def find_xray() -> Path | None:
    _copy_bundled_core_to_user_dir()
    name = "xray.exe" if is_windows() else "xray"
    candidates = [CORE_DIR / name, BUNDLED_CORE_DIR / name, APP_ROOT / "core" / name]
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and (is_windows() or os.access(candidate, os.X_OK)):
            return candidate
    return None


def _core_version_matches(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [str(executable), "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            cwd=str(executable.parent),
            creationflags=_creation_flags(),
        )
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"(?i)\bXray\s+(\d+\.\d+\.\d+)\b", output)
        return result.returncode == 0 and bool(match) and match.group(1) == XRAY_VERSION
    except Exception:
        return False


def _wintun_arch_folder() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"} or "64" in machine and "arm" not in machine:
        return "amd64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine.startswith("arm"):
        return "arm"
    return "x86"


def _verify_sha256(path: Path, expected: str, artifact: str = "artifact") -> None:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest().lower()
    if digest != expected.lower():
        raise RuntimeError("اعتبار فایل اتصال تأیید نشد")


def ensure_wintun(executable: Path, progress: Callable[[str], None] | None = None, force_download: bool = False, language: str = "fa") -> Path | None:
    if not is_windows():
        return None
    destination = executable.parent / "wintun.dll"
    if destination.exists() and destination.stat().st_size > 50_000 and not force_download:
        return destination

    candidates = [CORE_DIR / "wintun.dll", BUNDLED_CORE_DIR / "wintun.dll", APP_ROOT / "core" / "wintun.dll"]
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 50_000:
            if candidate.resolve() != destination.resolve():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, destination)
            return destination

    if progress:
        progress(tr(language, "downloading_wintun"))
    archive = CORE_DIR / "wintun.zip"
    _download_file(WINTUN_URL, archive, timeout=90)
    _verify_sha256(archive, WINTUN_SHA256, "Wintun")
    arch = _wintun_arch_folder()
    with zipfile.ZipFile(archive, "r") as package:
        names = package.namelist()
        preferred = [
            name
            for name in names
            if Path(name).name.lower() == "wintun.dll" and f"/{arch}/" in name.replace("\\", "/").lower()
        ]
        source_name = preferred[0] if preferred else next(
            (name for name in names if Path(name).name.lower() == "wintun.dll"),
            None,
        )
        if not source_name:
            raise RuntimeError("یکی از فایل‌های لازم اتصال پیدا نشد")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with package.open(source_name) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)
    archive.unlink(missing_ok=True)
    if not destination.exists() or destination.stat().st_size < 50_000:
        raise RuntimeError("بخش اتصال آماده نشد")
    return destination


def ensure_xray(
    progress: Callable[[str], None] | None = None,
    force_download: bool = False,
    language: str = "fa",
    *,
    require_wintun: bool = True,
) -> Path:
    existing = None if force_download else find_xray()
    if existing and _core_version_matches(existing):
        if require_wintun:
            ensure_wintun(existing, progress=progress, language=language)
        return existing
    if progress:
        progress(tr(language, "downloading_core"))
    archive = CORE_DIR / f"xray-{XRAY_VERSION}.zip"
    asset_name, url = _pinned_asset_url()
    expected = _XRAY_ARCHIVE_SHA256.get(asset_name)
    if not expected:
        raise RuntimeError(f"No pinned Xray digest exists for {asset_name}")
    _download_file(url, archive)
    try:
        _verify_sha256(archive, expected, "Xray")
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    executable = _extract_core(archive, CORE_DIR)
    archive.unlink(missing_ok=True)
    if require_wintun:
        ensure_wintun(executable, progress=progress, language=language)
    return executable


def _select_darwin_tun_name() -> str:
    """Choose a high, currently unused utun number for macOS."""
    occupied: set[str] = set()
    try:
        result = subprocess.run(
            ["ifconfig", "-l"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        occupied = set((result.stdout or "").split())
    except Exception:
        pass
    for number in range(233, 1024):
        candidate = f"utun{number}"
        if candidate not in occupied:
            return candidate
    return "utun233"


def _platform_tun_settings(
    *,
    platform_name: str | None = None,
    tun_name: str | None = None,
) -> dict[str, Any]:
    """Return a valid Xray TUN profile for Windows, Linux or macOS."""
    system = (platform_name or platform.system()).lower()
    settings: dict[str, Any] = {
        "mtu": 1400,
        "gateway": ["10.77.0.1/30", "fd77::1/126"],
        "userLevel": 0,
        "autoSystemRoutingTable": ["0.0.0.0/0", "::/0"],
        "autoOutboundsInterface": "auto",
    }
    if system.startswith("darwin") or system.startswith("mac"):
        settings["name"] = tun_name or _select_darwin_tun_name()
        # Xray currently applies only the IPv4 gateway on Darwin, but keeping
        # the IPv6 prefix is harmless and makes the intended no-leak route clear.
    else:
        settings["name"] = tun_name or TUN_NAME
    if system.startswith("win"):
        settings["desc"] = "dicodePing"
        settings["dns"] = ["1.1.1.1", "8.8.8.8"]
    return settings


def _source_ip_for_endpoint(host: str, port: int) -> str:
    """Resolve the physical source IP before the default route moves to TUN."""
    if not host:
        return ""
    try:
        infos = socket.getaddrinfo(host, int(port or 443), socket.AF_UNSPEC, socket.SOCK_DGRAM)
    except OSError:
        return ""
    for family, socktype, proto, _canonname, sockaddr in infos:
        try:
            with socket.socket(family, socktype, proto) as probe:
                probe.settimeout(1.5)
                probe.connect(sockaddr)
                value = str(probe.getsockname()[0])
                if value and value not in {"0.0.0.0", "::"}:
                    return value
        except OSError:
            continue
    return ""


_DIRECT_TUN_ENDPOINTS = (
    "https://www.google.com/generate_204",
    "https://www.gstatic.com/generate_204",
    "https://cp.cloudflare.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
    "https://api.github.com/zen",
)

_SOCKS_VALIDATION_TARGETS = (
    ("www.google.com", "/generate_204", True),
    ("www.gstatic.com", "/generate_204", True),
    ("cp.cloudflare.com", "/generate_204", True),
    ("www.cloudflare.com", "/cdn-cgi/trace", True),
)


def _direct_tun_single_probe(url: str, timeout: float) -> int | None:
    """Run one no-proxy request through the system route.

    This is intentionally a connectivity hint, not the sole source of truth:
    captive portals, regional filtering, DNS interception and endpoint-specific
    blocking can make any single public URL fail while the TUN is carrying real
    application traffic.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.perf_counter()
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"{APP_NAME}/{VERSION}", "Connection": "close"},
        )
        with opener.open(request, timeout=max(0.45, float(timeout))) as response:
            if 200 <= int(response.status) < 400:
                return max(1, int(round((time.perf_counter() - started) * 1000)))
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        return None
    return None


def _direct_tun_http_probe(timeout: float = 3.0) -> int | None:
    """Best-effort latency check through the active system-wide TUN route.

    ``timeout`` is a total budget, not a per-site multiplier. This prevents the
    post-connect UI check from blocking for many seconds when one public probe
    endpoint is filtered even though applications such as Telegram already work.
    """
    deadline = time.monotonic() + max(0.6, float(timeout))
    for url in _DIRECT_TUN_ENDPOINTS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = _direct_tun_single_probe(url, min(1.35, max(0.45, remaining)))
        if result is not None:
            return result
    return None


def build_tun_config(
    raw_config: str,
    bypass_domains: list[str] | tuple[str, ...] | str | None = None,
    api_port: int = 0,
    validation_socks_port: int = 0,
    secure_dns: bool = True,
    *,
    platform_name: str | None = None,
    tun_name: str | None = None,
    outbound_bind_ip: str = "",
) -> dict[str, Any]:
    resources = current_resource_profile()
    outbound = build_xray_outbound(raw_config)
    if not outbound:
        raise ValueError("این نوع کانفیگ توسط نسخه فعلی پشتیبانی نمی‌شود")
    if outbound_bind_ip:
        outbound["sendThrough"] = outbound_bind_ip
    stream = outbound.setdefault("streamSettings", {})
    if isinstance(stream, dict):
        sockopt = stream.setdefault("sockopt", {})
        if isinstance(sockopt, dict):
            sockopt.setdefault("domainStrategy", "UseIP")
            sockopt.setdefault(
                "happyEyeballs",
                {"tryDelayMs": 250, "prioritizeIPv6": False, "interleave": 1, "maxConcurrentTry": 4},
            )
            sockopt.setdefault("tcpKeepAliveIdle", 45)
            sockopt.setdefault("tcpKeepAliveInterval", 15)
            sockopt.setdefault("tcpUserTimeout", 15000)

    rules: list[dict[str, Any]] = []
    domains = normalize_bypass_domains(bypass_domains)
    if domains:
        rules.append(
            {
                "type": "field",
                "domain": [f"domain:{domain}" for domain in domains],
                "outboundTag": "direct",
            }
        )
    rules.append(
        {
            "type": "field",
            "ip": [
                "127.0.0.0/8",
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "169.254.0.0/16",
                "::1/128",
                "fc00::/7",
                "fe80::/10",
            ],
            "outboundTag": "direct",
        }
    )

    config: dict[str, Any] = {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": (
                [
                    {"address": "https://cloudflare-dns.com/dns-query", "domains": ["geosite:geolocation-!cn"]},
                    {"address": "https://dns.google/dns-query"},
                ]
                if secure_dns
                else [
                    {"address": "1.1.1.1", "skipFallback": False},
                    {"address": "8.8.8.8", "skipFallback": False},
                ]
            ),
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
                    "bufferSize": resources.network_buffer_kib,
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
                "settings": _platform_tun_settings(
                    platform_name=platform_name,
                    tun_name=tun_name,
                ),
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            }
        ],
        "outbounds": [outbound, {"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": rules},
    }
    if validation_socks_port:
        config["inbounds"].append(
            {
                "tag": "validation-socks",
                "listen": "127.0.0.1",
                "port": int(validation_socks_port),
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }
        )
    if api_port:
        config["api"] = {
            "tag": "api",
            "listen": f"127.0.0.1:{int(api_port)}",
            "services": ["StatsService"],
        }
        rules.append(
            {
                "type": "field",
                "inboundTag": ["api"],
                "outboundTag": "api",
            },
        )
    return config



def build_probe_config(raw_config: str, socks_port: int) -> dict[str, Any]:
    """Build a short-lived SOCKS profile for a real outbound latency probe.

    Unlike a TCP connect, this performs an HTTP request after the selected
    proxy protocol and transport have completed.  It is the same meaningful
    measurement used by modern Xray clients for server testing.
    """
    outbound = build_xray_outbound(raw_config)
    if not outbound:
        raise ValueError("Unsupported server configuration")
    stream = outbound.setdefault("streamSettings", {})
    if isinstance(stream, dict):
        stream.setdefault("sockopt", {"domainStrategy": "UseIP"})
    return {
        "log": {"loglevel": "none"},
        "dns": {"servers": ["1.1.1.1", "8.8.8.8"], "queryStrategy": "UseIP"},
        "inbounds": [{
            "listen": "127.0.0.1", "port": int(socks_port), "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        }],
        "outbounds": [outbound, {"tag": "direct", "protocol": "freedom"}],
        "routing": {"domainStrategy": "IPIfNonMatch"},
    }


def _http_proxy_probe(port: int, host: str, path: str, timeout: float) -> int | None:
    """Verify Xray's local HTTP inbound with a real proxied request."""
    started = time.perf_counter()
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            target = f"http://{host}{path}"
            request = (
                f"GET {target} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Connection: close\r\n"
                "Proxy-Connection: close\r\n"
                "User-Agent: dicodePing\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            header = sock.recv(128)
            if b" 204 " not in header and b" 200 " not in header:
                return None
            return max(1, int(round((time.perf_counter() - started) * 1000)))
    except (OSError, ValueError):
        return None


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    """Receive an exact number of bytes or fail cleanly.

    TCP is a byte stream, so a single ``recv(size)`` is not guaranteed to
    return ``size`` bytes.  The previous implementation occasionally parsed a
    fragmented SOCKS reply as a dead server even though Xray had connected.
    """
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("unexpected EOF")
        data.extend(chunk)
    return bytes(data)


def _read_http_status(sock: socket.socket, limit: int = 4096) -> int | None:
    data = bytearray()
    while b"\r\n" not in data and len(data) < limit:
        chunk = sock.recv(min(512, limit - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    first_line = bytes(data).split(b"\r\n", 1)[0]
    match = re.match(rb"HTTP/\d(?:\.\d)?\s+(\d{3})(?:\s|$)", first_line)
    return int(match.group(1)) if match else None


def _socks_connect(sock: socket.socket, host: str, target_port: int) -> bool:
    sock.sendall(b"\x05\x01\x00")
    if _recv_exact(sock, 2) != b"\x05\x00":
        return False
    encoded = host.encode("idna")
    if not encoded or len(encoded) > 255:
        return False
    sock.sendall(
        b"\x05\x01\x00\x03"
        + bytes([len(encoded)])
        + encoded
        + int(target_port).to_bytes(2, "big")
    )
    reply = _recv_exact(sock, 4)
    if reply[0] != 5 or reply[1] != 0:
        return False
    atyp = reply[3]
    if atyp == 1:
        _recv_exact(sock, 4)
    elif atyp == 4:
        _recv_exact(sock, 16)
    elif atyp == 3:
        _recv_exact(sock, _recv_exact(sock, 1)[0])
    else:
        return False
    _recv_exact(sock, 2)
    return True


def _socks_http_probe(
    port: int,
    host: str,
    path: str,
    timeout: float,
    *,
    use_tls: bool = False,
) -> int | None:
    """Perform a real HTTP request through Xray's private SOCKS inbound.

    HTTPS is preferred because some otherwise healthy servers or upstream
    networks block plain port 80. Certificate verification is intentionally
    disabled here: this is only a liveness/path probe, not a trust decision.
    """
    started = time.perf_counter()
    target_port = 443 if use_tls else 80
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as raw_sock:
            raw_sock.settimeout(timeout)
            if not _socks_connect(raw_sock, host, target_port):
                return None
            stream: socket.socket = raw_sock
            if use_tls:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                stream = context.wrap_socket(raw_sock, server_hostname=host)
                stream.settimeout(timeout)
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Connection: close\r\n"
                "User-Agent: dicodePing-connectivity-check\r\n"
                "Accept: */*\r\n\r\n"
            ).encode("ascii")
            stream.sendall(request)
            status = _read_http_status(stream)
            if status is None or not 200 <= status < 400:
                return None
            return max(1, int(round((time.perf_counter() - started) * 1000)))
    except (OSError, ValueError, ssl.SSLError, IndexError):
        return None


def probe_outbound_delay(
    raw_config: str,
    timeout: float = 3.2,
    cancel_event: threading.Event | None = None,
) -> int | None:
    """Measure verified proxy traffic without creating a TUN adapter."""
    if cancel_event is not None and cancel_event.is_set():
        return None
    # First-use extraction/download must be serialized; concurrent probe jobs
    # can otherwise race over the same core archive.
    with _PROBE_CORE_LOCK:
        executable = ensure_xray(language="en", require_wintun=False)
    port = PORT_REGISTRY.acquire()
    token = uuid.uuid4().hex
    config_path = RUNTIME_DIR / f"probe-{token}.json"
    process: subprocess.Popen[str] | None = None
    try:
        config_path.write_text(json.dumps(build_probe_config(raw_config, port), ensure_ascii=False), encoding="utf-8")
        process = PROCESS_REGISTRY.register(
            subprocess.Popen(
                [str(executable), "run", "-config", str(config_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(executable.parent),
                creationflags=_creation_flags(),
                start_new_session=not is_windows(),
            )
        )
        ready_until = time.monotonic() + min(3.5, max(2.0, timeout))
        targets = (
            ("www.gstatic.com", "/generate_204", True),
            ("cp.cloudflare.com", "/generate_204", True),
            ("www.cloudflare.com", "/cdn-cgi/trace", True),
            ("www.gstatic.com", "/generate_204", False),
        )
        while time.monotonic() < ready_until and process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                return None
            for host, path, use_tls in targets:
                result = _socks_http_probe(
                    port,
                    host,
                    path,
                    min(2.4 if use_tls else 1.8, max(1.0, timeout)),
                    use_tls=use_tls,
                )
                if result is not None:
                    return result
            time.sleep(0.10)
        return None
    except Exception:
        return None
    finally:
        PROCESS_REGISTRY.stop(process, timeout=0.8)
        PORT_REGISTRY.release(port)
        try:
            config_path.unlink(missing_ok=True)
        except OSError:
            pass


class XrayManager:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.config_path: Path | None = None
        self.log_handle = None
        self.token = ""
        self.executable: Path | None = None
        self.api_port = 0
        self.validation_socks_port = 0
        self.http_proxy_port = 0
        self.connected_host = ""
        self.connected_ip = ""
        self.connected_port = 0
        self._direct_routes: list[str] = []
        self._active_log_file = LOG_FILE
        self._retain_log = False
        self._cancel_start = threading.Event()
        self.route_mode = "disconnected"
        self._startup_verified = False
        self._startup_evidence = "none"
        self._last_verified_ping_ms: int | None = None
        self._last_verified_at = 0.0
        self._system_proxy = DesktopProxyController()
        # stop() may be reached by the Disconnect action, a monitor callback
        # and the process-exit handler at nearly the same time.  Serialize
        # teardown so one caller never closes routes/files owned by another.
        self._stop_lock = threading.RLock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_thread: threading.Thread | None = None
        atexit.register(self.stop)

    def _schedule_tun_cleanup(self) -> None:
        """Coalesce repeated disconnect cleanup into at most one worker."""
        with self._cleanup_lock:
            if self._cleanup_thread and self._cleanup_thread.is_alive():
                return

            def _cleanup() -> None:
                try:
                    cleanup_named_tun()
                finally:
                    with self._cleanup_lock:
                        self._cleanup_thread = None

            self._cleanup_thread = threading.Thread(
                target=_cleanup,
                name="dicodePing-tun-cleanup",
                daemon=True,
            )
            self._cleanup_thread.start()

    @property
    def connected(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    @property
    def startup_verified(self) -> bool:
        """Whether startup collected credible Xray/TUN evidence.

        This flag is set only after the Xray process is alive and at least one
        real path signal succeeds: a no-proxy TUN HTTP request, observed TUN
        traffic, or a verified private Xray SOCKS request after the automatic
        route configuration has had time to settle.
        """
        return bool(self.connected and self.route_mode.startswith("tun:") and self._startup_verified)

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
        # TCP application traffic is the strongest log signal. UDP is accepted
        # too because DNS/QUIC may be the first traffic generated after routing.
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
            creationflags=_creation_flags(),
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
        bypass_domains: list[str] | tuple[str, ...] | str | None = None,
        endpoint_host: str = "",
        endpoint_port: int = 0,
        secure_dns: bool = True,
        progress_value: Callable[[int, int], None] | None = None,
        core_options: dict[str, object] | None = None,
    ) -> None:
        # ``core_options`` is accepted for API compatibility with the shared
        # ConnectionManager facade. Xray does not consume alternative-core options.
        _ = core_options
        if not is_admin():
            raise RuntimeError(
                "برای اتصال TUN برنامه باید با دسترسی مدیر اجرا شود"
                if language != "en"
                else "Administrator/root privileges are required for TUN mode"
            )
        _emit_progress_value(progress_value, 8)
        with self._stop_lock:
            self.stop()
            cancel_start = threading.Event()
            self._cancel_start = cancel_start
            self._startup_verified = False
            self._startup_evidence = "none"
            self._last_verified_ping_ms = None
            self._last_verified_at = 0.0
        cleanup_stale_owned_process()
        executable = ensure_xray(
            progress,
            language=language,
            require_wintun=is_windows(),
        )
        if is_windows():
            wintun = ensure_wintun(executable, progress=progress, language=language)
            if not wintun or not wintun.exists():
                raise RuntimeError("فایل Wintun برای اتصال TUN آماده نیست")
        _emit_progress_value(progress_value, 22)
        if cancel_start.is_set():
            raise RuntimeError("راه‌اندازی اتصال لغو شد" if language != "en" else "Connection startup was cancelled")

        endpoint = parse_endpoint(raw_config)
        self.connected_host = endpoint_host or (endpoint.host if endpoint else "")
        self.connected_port = int(endpoint_port or (endpoint.port if endpoint else 0) or 0)
        endpoint_ips = resolve_all_ips(self.connected_host) if self.connected_host else []
        self.connected_ip = endpoint_ips[0] if endpoint_ips else ""
        outbound_bind_ip = _source_ip_for_endpoint(self.connected_host, self.connected_port)
        # A precise host route is a second loop-prevention layer in addition to
        # autoOutboundsInterface and sendThrough. It is removed on Disconnect.
        self._direct_routes = install_direct_host_routes(endpoint_ips, TUN_NAME, only_if_tun=False)
        _emit_progress_value(progress_value, 32)

        try:
            self.api_port = PORT_REGISTRY.acquire()
            self.validation_socks_port = PORT_REGISTRY.acquire()
            config = build_tun_config(
                raw_config,
                bypass_domains=bypass_domains,
                api_port=self.api_port,
                validation_socks_port=self.validation_socks_port,
                secure_dns=secure_dns,
                outbound_bind_ip=outbound_bind_ip,
            )
            tun_settings = config["inbounds"][0]["settings"]
            active_tun_name = str(tun_settings.get("name") or TUN_NAME)
            self.token = uuid.uuid4().hex
            self.config_path = RUNTIME_DIR / f"tun-{self.token}.json"
            self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            _emit_progress_value(progress_value, 42)
        except Exception:
            self.stop()
            raise

        validation = self._validate(executable, self.config_path)
        if cancel_start.is_set():
            self.stop()
            raise RuntimeError("راه‌اندازی اتصال لغو شد" if language != "en" else "Connection startup was cancelled")
        validation_text = (validation.stderr or validation.stdout or "").strip()
        if validation.returncode != 0 and any(
            token in validation_text.lower()
            for token in ("tun", "autosystemroutingtable", "unknown protocol", "failed to load")
        ):
            try:
                executable = ensure_xray(
                    progress,
                    force_download=True,
                    language=language,
                    require_wintun=is_windows(),
                )
                if is_windows():
                    ensure_wintun(executable, progress=progress, language=language, force_download=True)
                validation = self._validate(executable, self.config_path)
                validation_text = (validation.stderr or validation.stdout or "").strip()
            except Exception:
                pass
        _emit_progress_value(progress_value, 52)
        if validation.returncode != 0:
            error = (validation_text or "کانفیگ Xray نامعتبر است")[-1200:]
            LOGGER.error("TUN configuration validation failed: %s", error)
            self.stop()
            raise RuntimeError(
                "تنظیمات TUN یا کانفیگ این سرور معتبر نیست"
                if language != "en"
                else "The TUN or server configuration is invalid"
            )

        self._retain_log = diagnostics_enabled()
        self._active_log_file = LOG_FILE if self._retain_log else RUNTIME_DIR / "connection-session.log"
        self._active_log_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self._active_log_file.exists() and (not self._retain_log or self._active_log_file.stat().st_size > 2_000_000):
                self._active_log_file.write_text("", encoding="utf-8")
        except Exception:
            pass
        log_start_offset = self._active_log_file.stat().st_size if self._active_log_file.exists() else 0
        self.log_handle = self._active_log_file.open("a", encoding="utf-8")
        self.executable = executable
        try:
            self.process = PROCESS_REGISTRY.register(
                subprocess.Popen(
                    [str(executable), "run", "-config", str(self.config_path)],
                    stdout=self.log_handle,
                    stderr=self.log_handle,
                    cwd=str(executable.parent),
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    creationflags=_creation_flags(),
                    start_new_session=not is_windows(),
                )
            )
        except Exception:
            self.stop()
            raise
        if cancel_start.is_set():
            self.stop()
            raise RuntimeError("راه‌اندازی اتصال لغو شد" if language != "en" else "Connection startup was cancelled")
        _emit_progress_value(progress_value, 64)
        self.route_mode = f"tun-starting:{active_tun_name}"
        PID_FILE.write_text(
            json.dumps(
                {
                    "pid": self.process.pid,
                    "config_path": str(self.config_path),
                    "token": self.token,
                    "direct_routes": list(self._direct_routes),
                    "route_mode": self.route_mode,
                    "tun_name": active_tun_name,
                    "socks_port": self.validation_socks_port,
                }
            ),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 7.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            recent = ""
            try:
                with self._active_log_file.open("r", encoding="utf-8", errors="ignore") as handle:
                    handle.seek(log_start_offset)
                    recent = handle.read().lower()
            except Exception:
                recent = ""
            if "started" in recent or "starting core successfully" in recent:
                break
            time.sleep(0.12)

        if self.process.poll() is not None:
            code = self.process.returncode
            tail = self._read_log_tail()
            LOGGER.error("TUN process stopped with code %s: %s", code, tail[-1400:])
            self.stop()
            raise RuntimeError(
                "هسته Xray نتوانست رابط TUN را ایجاد کند؛ گزارش عیب‌یابی را بررسی کنید"
                if language != "en"
                else "Xray could not create the TUN interface; inspect diagnostic logs"
            )

        # RC19 stability hotfix: startup uses multiple independent signals and a
        # single short budget. Public connectivity endpoints are useful latency
        # hints, but they are not allowed to tear down a tunnel that is already
        # carrying real application traffic (for example Telegram).
        # Legacy audit markers retained for compatibility with earlier RC19 tests:
        # ("www.gstatic.com", "/generate_204", True)
        # Private SOCKS validation was inconclusive; continuing
        # A failed private probe must never tear down a working TUN.
        # _direct_tun_http_probe is now advisory; startup rotates single probes.
        _emit_progress_value(progress_value, 70)
        if progress:
            progress("در حال تأیید مسیر پایدار Xray و TUN…" if language != "en" else "Verifying stable Xray and TUN routing…")

        verification_started = time.monotonic()
        verification_deadline = verification_started + 13.0
        outbound_ping: int | None = None
        tun_ping: int | None = None
        evidence = ""
        target_index = 0

        while time.monotonic() < verification_deadline and self.process.poll() is None:
            if cancel_start.is_set():
                self.stop()
                raise RuntimeError("Connection startup was cancelled")

            # Real TUN packets are stronger evidence than reachability of one
            # vendor-controlled health URL. This catches the exact case where
            # Telegram works while generate_204 is blocked or intercepted.
            if self._tun_activity_observed():
                evidence = "tun-traffic"
                break

            host, path, use_tls = _SOCKS_VALIDATION_TARGETS[target_index % len(_SOCKS_VALIDATION_TARGETS)]
            if outbound_ping is None:
                outbound_ping = _socks_http_probe(
                    self.validation_socks_port,
                    host,
                    path,
                    1.45,
                    use_tls=use_tls,
                )

            url = _DIRECT_TUN_ENDPOINTS[target_index % len(_DIRECT_TUN_ENDPOINTS)]
            if tun_ping is None:
                tun_ping = _direct_tun_single_probe(url, 1.25)
            target_index += 1

            if tun_ping is not None:
                evidence = "tun-http"
                break

            elapsed = time.monotonic() - verification_started
            # Xray has accepted a real HTTPS request through its own outbound,
            # the TUN config passed ``xray run -test`` and the process stayed
            # alive after route installation. Treat this as a valid provisional
            # TUN startup instead of disconnecting a working tunnel because all
            # public no-proxy probes happened to be filtered.
            if outbound_ping is not None and elapsed >= 2.2:
                evidence = "xray-socks+configured-tun"
                break

            _emit_progress_value(progress_value, 76 + min(18, round((elapsed / 13.0) * 18)))
            time.sleep(0.12)

        if self.process.poll() is not None:
            tail = self._read_log_tail()
            self.stop()
            raise RuntimeError(
                "هسته Xray هنگام فعال‌سازی TUN متوقف شد؛ گزارش عیب‌یابی را بررسی کنید"
                if language != "en"
                else "Xray stopped while activating TUN; inspect diagnostic logs"
            )

        # One final packet/log check allows applications that started traffic
        # near the deadline to prove the route without another public HTTP call.
        if not evidence and self._tun_activity_observed():
            evidence = "tun-traffic"

        if not evidence:
            tail = self._read_log_tail()
            LOGGER.error("No credible Xray/TUN startup evidence: %s", tail[-1600:])
            self.stop()
            raise RuntimeError(
                "هسته Xray یا مسیر TUN هیچ ترافیک معتبری عبور نداد؛ کانفیگ سرور را تغییر دهید"
                if language != "en"
                else "Xray/TUN did not produce any credible traffic evidence; try another server"
            )

        self.route_mode = f"tun:{active_tun_name}"
        self._startup_verified = True
        self._startup_evidence = evidence
        self._last_verified_ping_ms = tun_ping if tun_ping is not None else outbound_ping
        self._last_verified_at = time.monotonic()
        LOGGER.info(
            "Xray TUN startup accepted: evidence=%s tun_ping=%s outbound_ping=%s",
            evidence,
            tun_ping,
            outbound_ping,
        )
        try:
            payload = json.loads(PID_FILE.read_text(encoding="utf-8"))
            payload["route_mode"] = self.route_mode
            payload["verified_ping_ms"] = self._last_verified_ping_ms
            payload["startup_evidence"] = evidence
            PID_FILE.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass
        _emit_progress_value(progress_value, 96)

    def traffic_stats(self) -> tuple[int | None, int | None]:
        if not self.connected or not self.executable or not self.api_port:
            return None, None
        try:
            result = subprocess.run(
                [
                    str(self.executable),
                    "api",
                    "statsquery",
                    f"--server=127.0.0.1:{self.api_port}",
                    "-timeout",
                    "1",
                    "-pattern",
                    "inbound>>>",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=1.0,
                cwd=str(self.executable.parent),
                creationflags=_creation_flags(),
            )
            text = (result.stdout or "").strip()
            begin, finish = text.find("{"), text.rfind("}")
            if begin < 0 or finish < begin:
                return None, None
            payload = json.loads(text[begin : finish + 1])
            upload = 0
            download = 0
            for item in payload.get("stat", []) if isinstance(payload, dict) else []:
                name = str(item.get("name") or "")
                if not any(
                    name.startswith(f"inbound>>>{tag}>>>traffic>>>")
                    for tag in ("tun-in",)
                ):
                    continue
                try:
                    value = int(item.get("value") or 0)
                except (TypeError, ValueError):
                    value = 0
                if name.endswith(">>>uplink"):
                    upload += value
                elif name.endswith(">>>downlink"):
                    download += value
            return max(0, upload), max(0, download)
        except Exception:
            return None, None

    def connected_ping(self, timeout: float = 1.0) -> int | None:
        """Measure TUN latency without converting endpoint filtering into a disconnect."""
        if not self.startup_verified:
            return None
        result = _direct_tun_http_probe(timeout=max(0.6, float(timeout)))
        if result is not None:
            self._last_verified_ping_ms = result
            self._last_verified_at = time.monotonic()
            return result
        # A failed public probe is not evidence that the VPN died. Keep the last
        # recent measurement while the process and TUN evidence are still valid.
        if self.connected and self._tun_activity_observed():
            self._last_verified_at = time.monotonic()
        if self._last_verified_ping_ms is not None and time.monotonic() - self._last_verified_at <= 90.0:
            return self._last_verified_ping_ms
        return None

    def stop(self) -> None:
        with self._stop_lock:
            needs_tun_cleanup = bool(
                self.process or self.config_path or self._direct_routes or self.route_mode.startswith("tun")
            )
            try:
                self._cancel_start.set()
                # Restore only a stale RC19 system-proxy snapshot, if one exists.
                # RC19 TUN mode itself never enables an operating-system proxy.
                try:
                    self._system_proxy.restore()
                except Exception:
                    LOGGER.debug("No stale system proxy state could be restored", exc_info=True)
                self.route_mode = "disconnected"
                self._startup_verified = False
                self._startup_evidence = "none"
                self._last_verified_ping_ms = None
                self._last_verified_at = 0.0
                process = self.process
                self.process = None
                PROCESS_REGISTRY.stop(process, timeout=2.5)
                # Close log handle before unlinking to avoid Windows file lock.
                try:
                    if self.log_handle:
                        try:
                            self.log_handle.flush()
                        except Exception:
                            pass
                        self.log_handle.close()
                except Exception:
                    pass
                self.log_handle = None
                if not self._retain_log:
                    try:
                        self._active_log_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                try:
                    PID_FILE.unlink(missing_ok=True)
                except Exception:
                    pass
                if self.config_path:
                    try:
                        self.config_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                self.config_path = None
                if self._direct_routes:
                    try:
                        remove_direct_host_routes(self._direct_routes)
                    except Exception:
                        LOGGER.exception("Direct route cleanup failed")
                self._direct_routes = []
                self.executable = None
                if self.api_port:
                    PORT_REGISTRY.release(self.api_port)
                if self.validation_socks_port:
                    PORT_REGISTRY.release(self.validation_socks_port)
                if self.http_proxy_port:
                    PORT_REGISTRY.release(self.http_proxy_port)
                self.api_port = 0
                self.validation_socks_port = 0
                self.http_proxy_port = 0
                self.connected_host = ""
                self.connected_ip = ""
                self.connected_port = 0
            except Exception:
                # stop() must NEVER raise; it is invoked from the UI thread,
                # monitor callbacks and atexit. A crash here takes the whole
                # process down on Disconnect which is what users reported.
                LOGGER.exception("Disconnect teardown failed but was contained")
            finally:
                # Defer the PowerShell-driven TUN cleanup off the caller's
                # thread so the Disconnect button never appears to hang and a
                # failing PowerShell invocation cannot crash the GUI.
                try:
                    if needs_tun_cleanup:
                        self._schedule_tun_cleanup()
                except Exception:
                    try:
                        if needs_tun_cleanup:
                            cleanup_named_tun()
                    except Exception:
                        pass
