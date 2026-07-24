from __future__ import annotations

import atexit
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
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
    if is_admin():
        return False
    if is_windows():
        executable = sys.executable
        if getattr(sys, "frozen", False):
            parameters = subprocess.list2cmdline(sys.argv[1:])
        else:
            parameters = subprocess.list2cmdline([str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters, str(APP_ROOT), 1)
        return int(result) > 32

    # Linux TUN creation needs CAP_NET_ADMIN. Prefer the desktop's PolicyKit
    # prompt and preserve only the display/session variables needed by Qt.
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return False
    command = [sys.executable, *sys.argv[1:]] if getattr(sys, "frozen", False) else [
        sys.executable,
        str(Path(sys.argv[0]).resolve()),
        *sys.argv[1:],
    ]
    environment = [
        f"DISPLAY={os.environ.get('DISPLAY', '')}",
        f"XAUTHORITY={os.environ.get('XAUTHORITY', '')}",
        f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '')}",
        f"XDG_RUNTIME_DIR={os.environ.get('XDG_RUNTIME_DIR', '')}",
    ]
    try:
        subprocess.Popen([pkexec, "env", *environment, *command], start_new_session=True)
        return True
    except OSError:
        return False


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
    safe_name = TUN_NAME.replace("'", "''")
    script = f"""
$ErrorActionPreference='SilentlyContinue'
Get-NetRoute -InterfaceAlias '{safe_name}' | Remove-NetRoute -Confirm:$false
Get-NetIPInterface -InterfaceAlias '{safe_name}' | Set-NetIPInterface -Dhcp Disabled
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


def ensure_xray(progress: Callable[[str], None] | None = None, force_download: bool = False, language: str = "fa") -> Path:
    existing = None if force_download else find_xray()
    if existing and _core_version_matches(existing):
        ensure_wintun(existing, progress=progress, language=language)
        return existing
    if progress:
        progress(tr(language, "downloading_core"))
    archive = CORE_DIR / f"xray-{XRAY_VERSION}.zip"
    digest_file = CORE_DIR / f"xray-{XRAY_VERSION}.zip.dgst"
    _name, url = _pinned_asset_url()
    _download_file(url, archive)
    try:
        _download_file(f"{url}.dgst", digest_file, timeout=45)
        expected = _parse_sha256_digest(digest_file.read_text(encoding="utf-8", errors="ignore"))
        _verify_sha256(archive, expected, "Xray")
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    finally:
        digest_file.unlink(missing_ok=True)
    executable = _extract_core(archive, CORE_DIR)
    archive.unlink(missing_ok=True)
    ensure_wintun(executable, progress=progress, language=language)
    return executable


def build_tun_config(
    raw_config: str,
    bypass_domains: list[str] | tuple[str, ...] | str | None = None,
    api_port: int = 0,
) -> dict[str, Any]:
    outbound = build_xray_outbound(raw_config)
    if not outbound:
        raise ValueError("این نوع کانفیگ توسط نسخه فعلی پشتیبانی نمی‌شود")
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
            "servers": [
                {"address": "1.1.1.1", "skipFallback": False},
                {"address": "8.8.8.8", "skipFallback": False},
            ],
            "queryStrategy": "UseIP",
        },
        "stats": {},
        "policy": {
            "levels": {
                "0": {"handshake": 8, "connIdle": 300, "uplinkOnly": 2, "downlinkOnly": 2}
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
                "protocol": "tun",
                "settings": {
                    "name": TUN_NAME,
                    "mtu": 1400,
                    "gateway": ["10.77.0.1/30", "fd77::1/126"],
                    "dns": ["1.1.1.1", "8.8.8.8"],
                    "autoSystemRoutingTable": ["0.0.0.0/0", "::/0"],
                    "autoOutboundsInterface": "auto",
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            }
        ],
        "outbounds": [outbound, {"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": rules},
    }
    if api_port:
        config["api"] = {
            "tag": "api",
            "listen": f"127.0.0.1:{int(api_port)}",
            "services": ["StatsService"],
        }
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


def _socks_http_probe(port: int, host: str, path: str, timeout: float) -> int | None:
    started = time.perf_counter()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"\x05\x01\x00")
            if sock.recv(2) != b"\x05\x00":
                return None
            encoded = host.encode("idna")
            sock.sendall(b"\x05\x01\x00\x03" + bytes([len(encoded)]) + encoded + (80).to_bytes(2, "big"))
            reply = sock.recv(4)
            if len(reply) != 4 or reply[1] != 0:
                return None
            atyp = reply[3]
            trailing = 4 if atyp == 1 else 16 if atyp == 4 else (sock.recv(1)[0] if atyp == 3 else 0)
            if trailing:
                sock.recv(trailing + 2)
            request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nUser-Agent: dicodePing\r\n\r\n".encode()
            sock.sendall(request)
            header = sock.recv(64)
            if b" 204 " not in header and b" 200 " not in header:
                return None
            return max(1, int(round((time.perf_counter() - started) * 1000)))
    except (OSError, ValueError):
        return None


def probe_outbound_delay(raw_config: str, timeout: float = 3.2) -> int | None:
    """Measure verified proxy traffic without creating a TUN adapter."""
    # First-use extraction/download must be serialized; concurrent probe jobs
    # can otherwise race over the same core archive.
    with _PROBE_CORE_LOCK:
        executable = ensure_xray(language="en")
    port = _free_local_port()
    token = uuid.uuid4().hex
    config_path = RUNTIME_DIR / f"probe-{token}.json"
    process: subprocess.Popen[str] | None = None
    try:
        config_path.write_text(json.dumps(build_probe_config(raw_config, port), ensure_ascii=False), encoding="utf-8")
        process = subprocess.Popen(
            [str(executable), "run", "-config", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(executable.parent),
            creationflags=_creation_flags(),
            start_new_session=not is_windows(),
        )
        ready_until = time.monotonic() + min(2.0, timeout)
        while time.monotonic() < ready_until and process.poll() is None:
            result = _socks_http_probe(port, "www.gstatic.com", "/generate_204", min(1.3, timeout))
            if result is not None:
                return result
            time.sleep(0.08)
        if process.poll() is None:
            return _socks_http_probe(port, "cp.cloudflare.com", "/generate_204", timeout)
        return None
    except Exception:
        return None
    finally:
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=0.8)
            except Exception:
                _kill_pid_tree(process.pid)
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
        self.connected_host = ""
        self.connected_ip = ""
        self.connected_port = 0
        self._direct_routes: list[str] = []
        self._active_log_file = LOG_FILE
        self._retain_log = False
        self._cancel_start = threading.Event()
        # stop() may be reached by the Disconnect action, a monitor callback
        # and the process-exit handler at nearly the same time.  Serialize
        # teardown so one caller never closes routes/files owned by another.
        self._stop_lock = threading.RLock()
        atexit.register(self.stop)

    @property
    def connected(self) -> bool:
        return bool(self.process and self.process.poll() is None)

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
    ) -> None:
        # Every attempt owns a cancellation token. Clearing and reusing the
        # old Event could erase a concurrent Disconnect request.
        with self._stop_lock:
            self.stop()
            cancel_start = threading.Event()
            self._cancel_start = cancel_start
        cleanup_stale_owned_process()
        executable = ensure_xray(progress, language=language)
        if cancel_start.is_set():
            raise RuntimeError("راه‌اندازی اتصال لغو شد" if language != "en" else "Connection startup was cancelled")
        wintun = ensure_wintun(executable, progress=progress, language=language)
        if is_windows() and (not wintun or not wintun.exists()):
            raise RuntimeError("یکی از بخش‌های لازم اتصال آماده نشد")

        endpoint = parse_endpoint(raw_config)
        self.connected_host = endpoint_host or (endpoint.host if endpoint else "")
        self.connected_port = int(endpoint_port or (endpoint.port if endpoint else 0) or 0)
        endpoint_ips = resolve_all_ips(self.connected_host) if self.connected_host else []
        self.connected_ip = endpoint_ips[0] if endpoint_ips else ""
        if endpoint_ips:
            self._direct_routes = install_direct_host_routes(endpoint_ips, TUN_NAME, only_if_tun=False)

        try:
            self.api_port = _free_local_port()
            config = build_tun_config(raw_config, bypass_domains=bypass_domains, api_port=self.api_port)
            self.token = uuid.uuid4().hex
            self.config_path = RUNTIME_DIR / f"tun-{self.token}.json"
            self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            self.stop()
            raise

        validation = self._validate(executable, self.config_path)
        if cancel_start.is_set():
            self.stop()
            raise RuntimeError("راه‌اندازی اتصال لغو شد" if language != "en" else "Connection startup was cancelled")
        validation_text = (validation.stderr or validation.stdout or "").strip()
        if validation.returncode != 0 and any(token in validation_text.lower() for token in ("tun", "autosystemroutingtable", "unknown protocol")):
            try:
                executable = ensure_xray(progress, force_download=True, language=language)
                ensure_wintun(executable, progress=progress, language=language)
                validation = self._validate(executable, self.config_path)
                validation_text = (validation.stderr or validation.stdout or "").strip()
            except Exception:
                pass
        if validation.returncode != 0:
            error = (validation_text or "کانفیگ Xray نامعتبر است")[-1200:]
            LOGGER.error("Connection configuration validation failed: %s", error)
            self.stop()
            raise RuntimeError("تنظیمات این سرور برای اتصال قابل استفاده نیست" if language != "en" else "This server cannot be used for a connection")

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
            self.process = subprocess.Popen(
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
        except Exception:
            self.stop()
            raise
        if cancel_start.is_set():
            self.stop()
            raise RuntimeError("راه‌اندازی اتصال لغو شد" if language != "en" else "Connection startup was cancelled")
        PID_FILE.write_text(
            json.dumps(
                {
                    "pid": self.process.pid,
                    "config_path": str(self.config_path),
                    "token": self.token,
                    "direct_routes": list(self._direct_routes),
                }
            ),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 6.0
        stable_since = time.monotonic()
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
            if time.monotonic() - stable_since >= 1.4:
                break
            time.sleep(0.1)

        if self.process.poll() is not None:
            code = self.process.returncode
            tail = self._read_log_tail()
            LOGGER.error("Connection process stopped with code %s: %s", code, tail[-1100:])
            self.stop()
            raise RuntimeError("بخش اتصال آماده نشد؛ در صورت تکرار، گزارش عیب‌یابی را فعال کنید" if language != "en" else "The connection could not start; enable diagnostic logging if this repeats")

    def traffic_stats(self) -> tuple[int, int]:
        if not self.connected or not self.executable or not self.api_port:
            return 0, 0
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
                    "inbound>>>tun-in>>>traffic>>>",
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
                return 0, 0
            payload = json.loads(text[begin : finish + 1])
            upload = 0
            download = 0
            for item in payload.get("stat", []) if isinstance(payload, dict) else []:
                name = str(item.get("name") or "")
                if not name.startswith("inbound>>>tun-in>>>traffic>>>"):
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
            return 0, 0

    def connected_ping(self, timeout: float = 1.0) -> int | None:
        if not self.connected or not self.connected_port or not (self.connected_ip or self.connected_host):
            return None
        target = self.connected_ip or self.connected_host
        started = time.perf_counter()
        try:
            with socket.create_connection((target, self.connected_port), timeout=timeout):
                return max(1, int(round((time.perf_counter() - started) * 1000)))
        except OSError:
            return None

    def stop(self) -> None:
        with self._stop_lock:
            try:
                self._cancel_start.set()
                process = self.process
                self.process = None
                if process and process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=2.5)
                    except Exception:
                        try:
                            _kill_pid_tree(process.pid)
                        except Exception:
                            LOGGER.debug("PID tree kill failed", exc_info=True)
                        try:
                            process.wait(timeout=1.0)
                        except Exception:
                            pass
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
                self.api_port = 0
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
                    threading.Thread(
                        target=cleanup_named_tun,
                        name="dicodePing-tun-cleanup",
                        daemon=True,
                    ).start()
                except Exception:
                    try:
                        cleanup_named_tun()
                    except Exception:
                        pass
