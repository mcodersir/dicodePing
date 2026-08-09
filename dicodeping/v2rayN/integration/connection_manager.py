"""v2rayN-based connection manager for dicodePing Version 3.

Manages the connection lifecycle, WARP registration, and
proxy configuration for the v2rayN stack.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .core_manager import core_dir, get_active_core, resolve_core_path
from dicodeping.core_runtime import CoreState, LifecycleController, PORT_REGISTRY, PROCESS_REGISTRY
from dicodeping.diagnostics import get_logger
from .xray import XrayManager

LOGGER = get_logger("connection_manager")


def _emit_progress(callback: Callable[[int, int], None] | None, current: int, total: int = 100) -> None:
    if callback is None:
        return
    try:
        callback(max(0, int(current)), max(1, int(total)))
    except Exception:
        LOGGER.debug("Progress callback failed", exc_info=True)


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def register_warp(*, accept_terms: bool) -> Path:
    """Register Usque atomically after explicit Cloudflare ToS consent."""
    if not accept_terms:
        raise RuntimeError("Cloudflare terms must be accepted before WARP registration")
    executable = resolve_core_path("warp")
    if executable is None:
        raise RuntimeError("WARP / Usque core is not installed")
    destination = core_dir("warp") / "config.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        try:
            payload = json.loads(destination.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("private_key") and payload.get("endpoint_pub_key"):
                return destination
        except Exception:
            pass

    temporary = destination.with_name("config.registering.json")
    last_error = "WARP registration failed"
    for attempt in range(2):
        temporary.unlink(missing_ok=True)
        result = subprocess.run(
            [
                str(executable),
                "-c",
                str(temporary),
                "register",
                "--accept-tos",
                "--name",
                "dicodePing",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=90,
            cwd=str(executable.parent),
            creationflags=_creation_flags(),
        )
        try:
            if result.returncode != 0 or not temporary.is_file():
                last_error = (result.stderr or result.stdout or last_error)[-1200:]
            else:
                payload = json.loads(temporary.read_text(encoding="utf-8"))
                if (
                    isinstance(payload, dict)
                    and payload.get("private_key")
                    and payload.get("endpoint_pub_key")
                    and payload.get("ipv4")
                ):
                    temporary.replace(destination)
                    return destination
                last_error = "WARP registration returned an incomplete configuration"
        except Exception as exc:
            last_error = str(exc)
        finally:
            temporary.unlink(missing_ok=True)
        if attempt == 0:
            time.sleep(1.5)
    raise RuntimeError(last_error)


def _socks5_connect(port: int, host: str, target_port: int, timeout: float) -> socket.socket:
    """Perform a SOCKS5 connection to the given host."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        sock.sendall(b"\x05\x01\x00")
        if sock.recv(2) != b"\x05\x00":
            raise OSError("SOCKS5 authentication negotiation failed")
        encoded = host.encode("idna")
        if len(encoded) > 255:
            raise OSError("SOCKS5 hostname is too long")
        sock.sendall(b"\x05\x01\x00\x03" + bytes((len(encoded),)) + encoded + struct.pack("!H", target_port))
        header = sock.recv(4)
        if len(header) != 4 or header[1] != 0:
            raise OSError("SOCKS5 connection was rejected")
        address_type = header[3]
        if address_type == 1:
            remaining = 4
        elif address_type == 4:
            remaining = 16
        elif address_type == 3:
            length = sock.recv(1)
            if not length:
                raise OSError("invalid SOCKS5 response")
            remaining = length[0]
        else:
            raise OSError("invalid SOCKS5 address type")
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise OSError("truncated SOCKS5 response")
            remaining -= len(chunk)
        if len(sock.recv(2)) != 2:
            raise OSError("truncated SOCKS5 port")
        return sock
    except Exception:
        sock.close()
        raise


def _http_probe_through_socks(port: int, timeout: float = 5.0) -> int | None:
    """Probe HTTP through a SOCKS5 proxy."""
    for host, path in (("captive.apple.com", "/hotspot-detect.html"), ("www.gstatic.com", "/generate_204"), ("cp.cloudflare.com", "/generate_204")):
        started = time.perf_counter()
        try:
            with _socks5_connect(port, host, 80, timeout) as sock:
                request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nUser-Agent: dicodePing/1.9\r\n\r\n".encode()
                sock.sendall(request)
                status = sock.recv(128)
                if status.startswith((b"HTTP/1.1 2", b"HTTP/1.0 2", b"HTTP/1.1 3")):
                    return max(1, round((time.monotonic() - started) * 1000))
        except OSError:
            continue
    return None


class DesktopProxyController:
    """Set and restore a desktop SOCKS proxy without leaving stale settings."""

    def __init__(self) -> None:
        self._windows_previous: tuple[int, str] | None = None
        self._gnome_previous: dict[str, str] | None = None
        self._mac_previous: dict[str, tuple[bool, str, str]] = {}

    @staticmethod
    def _value_exists(key: str, name: str) -> bool:
        try:
            import winreg
            winreg.QueryValueEx(key, name)
            return True
        except OSError:
            return False

    def enable(self, port: int) -> None:
        """Enable the SOCKS proxy on the system."""
        if os.name == "nt":
            import ctypes
            import winreg
            path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
                enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0]) if self._value_exists(key, "ProxyEnable") else 0
                server = str(winreg.QueryValueEx(key, "ProxyServer")[0]) if self._value_exists(key, "ProxyServer") else ""
                self._windows_previous = (enabled, server)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"socks=127.0.0.1:{port}")
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
            return
        if sys.platform == "darwin" and shutil.which("networksetup"):
            listing = subprocess.run(
                ["networksetup", "-listallnetworkservices"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.splitlines()[1:]
            services = [line.strip().lstrip("*").strip() for line in listing if line.strip()]
            for service in services:
                state = subprocess.run(
                    ["networksetup", "-getsocksfirewallproxy", service],
                    capture_output=True, text=True, timeout=5,
                ).stdout
                values = {}
                for line in state.splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        values[key.strip()] = value.strip()
                self._mac_previous[service] = (
                    values.get("Enabled", "No").lower() == "yes",
                    values.get("Server", ""),
                    values.get("Port", "0"),
                )
                subprocess.run(
                    ["networksetup", "-setsocksfirewallproxy", service, "127.0.0.1", str(port)],
                    check=True, timeout=5,
                )
                subprocess.run(
                    ["networksetup", "-setsocksfirewallproxystate", service, "on"],
                    check=True, timeout=5,
                )
            return
        if shutil.which("gsettings"):
            keys = {
                "mode": ("org.gnome.system.proxy", "mode"),
                "host": ("org.gnome.system.proxy.socks", "host"),
                "port": ("org.gnome.system.proxy.socks", "port"),
            }
            self._gnome_previous = {
                name: subprocess.run(
                    ["gsettings", "get", schema, key],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip()
                for name, (schema, key) in keys.items()
            }
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "host", "127.0.0.1"], check=True)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "port", str(port)], check=True)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"], check=True)

    def restore(self) -> None:
        """Restore the system proxy settings to their previous state."""
        if os.name == "nt" and self._windows_previous is not None:
            enabled, server = self._windows_previous
            path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, enabled)
            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
            self._windows_previous = None
        if self._mac_previous and shutil.which("networksetup"):
            for service, (enabled, host, port) in self._mac_previous.items():
                if host and port and port != "0":
                    subprocess.run(
                        ["networksetup", "-setsocksfirewallproxy", service, host, port],
                        check=False, timeout=5,
                    )
                subprocess.run(
                    ["networksetup", "-setsocksfirewallproxystate", service, "on" if enabled else "off"],
                    check=False, timeout=5,
                )
            self._mac_previous.clear()
        if self._gnome_previous is not None and shutil.which("gsettings"):
            previous = self._gnome_previous
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "host", previous["host"]], check=False)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "port", previous["port"]], check=False)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", previous["mode"]], check=False)
            self._gnome_previous = None


class AlternativeCoreManager:
    """Alternative core manager for non-Xray cores (Aether, WARP, Psiphon)."""

    def __init__(self, core_id: str) -> None:
        self.core_id = core_id
        self.process: subprocess.Popen[str] | None = None
        self.socks_port = 0
        self._log_handle: Optional[textio.TextIOWrapper] = None
        self._lock = threading.RLock()
        self._system_proxy = DesktopProxyController()
        self._options: dict[str, object] = {}
        self.lifecycle = LifecycleController()
        atexit.register(self.stop)

    @property
    def connected(self) -> bool:
        return bool(
            self.lifecycle.status.state == CoreState.CONNECTED
            and self.process
            and self.process.poll() is None
        )

    @property
    def state(self) -> CoreState:
        return self.lifecycle.status.state

    def start(
        self,
        _raw_config: str = "",
        progress: Callable[[str], None] | None = None,
        progress_value: Callable[[int, int], None] | None = None,
        core_options: dict[str, object] | None = None,
        language: str = "fa",
        **_kwargs,
    ) -> None:
        """Start an alternative core connection."""
        self.stop()
        token = self.lifecycle.begin(CoreState.STARTING)
        with self._lock:
            self._options = dict(core_options or {})
        _emit_progress(progress_value, 8)
        executable = resolve_core_path(self.core_id)
        if executable is None:
            self.lifecycle.fail(token, f"{self.core_id} core is not downloaded")
            raise RuntimeError(f"{self.core_id} core is not downloaded")
        runtime = core_dir(self.core_id) / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        log_path = runtime / "session.log"
        with self._lock:
            self._log_handle = log_path.open("w", encoding="utf-8")
            self.socks_port = PORT_REGISTRY.acquire()
        environment = os.environ.copy()
        _emit_progress(progress_value, 15)
        try:
            requested_transport = str(self._options.get("transport", "auto"))
            protocol = str(self._options.get("protocol", "masque"))
            if self.core_id == "aether" and protocol != "masque":
                transports = ["quic"]
            else:
                transports = ["http2"] if requested_transport == "http2" else ["quic", "http2"]
            scan = str(self._options.get("scan", "balanced"))
            initial_timeout = {
                "turbo": 20,
                "balanced": 30,
                "thorough": 42,
                "stealth": 50,
                "ironclad": 62,
            }.get(scan, 30)
            performance = str(self._options.get("performance", "auto"))
            probe_timeout, poll_interval = {
                "low": (1.55, 0.34),
                "medium": (1.15, 0.20),
                "high": (0.85, 0.12),
                "auto": (1.10, 0.18),
            }.get(performance, (1.10, 0.18))

            for attempt, transport in enumerate(transports):
                token.raise_if_cancelled()
                if attempt:
                    with self._lock:
                        old_process, self.process = self.process, None
                    PROCESS_REGISTRY.stop(old_process, timeout=3)
                label = "HTTP/2" if transport == "http2" else "HTTP/3 / QUIC"
                if progress:
                    progress(
                        f"در حال راه‌اندازی {self.core_id} با {label}…"
                        if language != "en" else f"Starting {self.core_id} over {label}…"
                    )
                base = 20 if attempt == 0 else 56
                ceiling = 54 if attempt == 0 else 82
                _emit_progress(progress_value, base)
                child = PROCESS_REGISTRY.register(
                    subprocess.Popen(
                        self._command(executable, runtime, environment, transport=transport),
                        stdout=self._log_handle,
                        stderr=self._log_handle,
                        stdin=subprocess.DEVNULL,
                        cwd=str(executable.parent),
                        env=environment,
                        text=True,
                        encoding="utf-8",
                        errors="ignore",
                        creationflags=_creation_flags(),
                        start_new_session=os.name != "nt",
                    )
                )
                with self._lock:
                    if token.is_cancelled():
                        PROCESS_REGISTRY.stop(child, timeout=1)
                        raise RuntimeError("Connection cancelled")
                    self.process = child
                self.lifecycle.transition(token, CoreState.VALIDATING)
                timeout = initial_timeout if attempt == 0 else max(34, initial_timeout - 8)
                deadline = time.monotonic() + timeout
                next_stage_at = 0.0
                while time.monotonic() < deadline:
                    token.raise_if_cancelled()
                    with self._lock:
                        current = self.process
                    if current is not child or child.poll() is not None:
                        tail = log_path.read_text(encoding="utf-8", errors="ignore")[-1800:]
                        if attempt + 1 < len(transports):
                            break
                        raise RuntimeError(f"{self.core_id} stopped during startup: {tail}")
                    elapsed = timeout - max(0.0, deadline - time.monotonic())
                    ratio = min(1.0, elapsed / max(1.0, timeout))
                    _emit_progress(progress_value, round(base + (ceiling - base) * ratio))
                    now = time.monotonic()
                    if progress and now >= next_stage_at:
                        seconds_left = max(0, round(deadline - now))
                        progress(
                            f"در حال اعتبارسنجی اتصال {self.core_id}؛ حدود {seconds_left} ثانیه…"
                            if language != "en" else f"Validating {self.core_id}; about {seconds_left}s remaining…"
                        )
                        next_stage_at = now + 3.0
                    if _http_probe_through_socks(self.socks_port, timeout=probe_timeout) is not None:
                        token.raise_if_cancelled()
                        _emit_progress(progress_value, 88)
                        if progress:
                            progress("در حال فعال‌سازی پروکسی سیستم…" if language != "en" else "Enabling the system proxy…")
                        self._system_proxy.enable(self.socks_port)
                        self.lifecycle.transition(token, CoreState.CONNECTED)
                        _emit_progress(progress_value, 94)
                        return
                    token.wait(poll_interval)

                if attempt + 1 < len(transports):
                    if progress:
                        progress(
                            f"{self.core_id} با QUIC پاسخ نداد؛ تلاش سریع با HTTP/2…"
                            if language != "en" else f"{self.core_id} did not validate over QUIC; retrying over HTTP/2…"
                        )
                    continue
                tail = log_path.read_text(encoding="utf-8", errors="ignore")[-1800:]
                raise RuntimeError(f"{self.core_id} did not establish verified HTTP traffic via {label}: {tail}")
        except Exception as exc:
            if not token.is_cancelled():
                self.lifecycle.fail(token, exc)
            self._teardown()
            raise

    def _command(
        self,
        executable: Path,
        runtime: Path,
        environment: dict[str, str],
        *,
        transport: str = "quic",
    ) -> list[str]:
        if self.core_id == "aether":
            protocol = str(self._options.get("protocol", "masque"))
            if protocol not in {"masque", "wireguard", "gool"}:
                protocol = "masque"
            protocol_flag = {"masque": "--masque", "wireguard": "--wg", "gool": "--gool"}[protocol]
            scan = str(self._options.get("scan", "balanced"))
            if scan not in {"turbo", "balanced", "thorough", "stealth", "ironclad"}:
                scan = "balanced"
            quick_reconnect = bool(self._options.get("quick_reconnect", True))
            config_path = core_dir("aether") / "aether.toml"
            environment.update(
                {
                    "AETHER_PROTOCOL": "wg" if protocol == "wireguard" else protocol,
                    "AETHER_SCAN": scan,
                    "AETHER_SOCKS": f"127.0.0.1:{self.socks_port}",
                    "AETHER_CONFIG": str(config_path),
                    "AETHER_QUICK_RECONNECT": "1" if quick_reconnect else "0",
                    "AETHER_NOIZE": "firewall" if protocol == "masque" else "balanced",
                    "AETHER_MASQUE_HTTP2": "1" if transport == "http2" and protocol == "masque" else "0",
                    "AETHER_PERF": str(self._options.get("performance", "auto")),
                }
            )
            command = [
                str(executable),
                "--config",
                str(config_path),
                protocol_flag,
                "-4",
                "--scan",
                scan,
                "--bind",
                f"127.0.0.1:{self.socks_port}",
                "--noize",
                "firewall" if protocol == "masque" else "balanced",
                "--quick-reconnect" if quick_reconnect else "--no-quick-reconnect",
            ]
            if transport == "http2" and protocol == "masque":
                command.append("--h2")
            return command
        if self.core_id == "warp":
            config = core_dir("warp") / "config.json"
            if not config.is_file():
                raise RuntimeError("WARP registration is required; activate it from Settings first")
            command = [
                str(executable),
                "-c", str(config),
                "socks",
                "-b", "127.0.0.1",
                "-p", str(self.socks_port),
                "--always-reconnect",
                "--reconnect-delay", "1s",
            ]
            if transport == "http2":
                command.append("--http2")
            return command
        if self.core_id == "psiphon":
            config = core_dir("psiphon") / "client.config"
            if not config.is_file():
                self.lifecycle.status.state = CoreState.MISSING_AUTHORIZED_CONFIG
                raise RuntimeError("Authorized Psiphon distribution configuration is unavailable in this build.")
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["LocalSocksProxyPort"] = self.socks_port
            session_config = runtime / "client.config"
            session_config.write_text(json.dumps(payload), encoding="utf-8")
            return [str(executable), "-config", str(session_config), "-dataRootDirectory", str(runtime)]
        raise RuntimeError(f"unsupported alternative core: {self.core_id}")

    def verify_connection(self) -> bool:
        return self.connected_ping(3.5) is not None

    def connected_ping(self, timeout: float = 1.0) -> int | None:
        if not self.process or self.process.poll() is not None or not self.socks_port:
            return None
        return _http_probe_through_socks(self.socks_port, timeout=max(0.4, timeout))

    def traffic_stats(self) -> tuple[int | None, int | None]:
        return (None, None)

    def stop(self) -> None:
        self.lifecycle.cancel()
        self.lifecycle.status.state = CoreState.STOPPING
        self._teardown()
        self.lifecycle.status.state = CoreState.DISCONNECTED

    def _teardown(self) -> None:
        self._system_proxy.restore()
        with self._lock:
            process, self.process = self.process, None
            port, self.socks_port = self.socks_port, 0
            log_handle, self._log_handle = self._log_handle, None
        PROCESS_REGISTRY.stop(process, timeout=2)
        if port:
            PORT_REGISTRY.release(port)
        if log_handle:
            try:
                log_handle.close()
            except Exception:
                pass


class ConnectionManager:
    """Stable facade that guarantees exactly one active core."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._manager: XrayManager | AlternativeCoreManager = self._new_manager()
        atexit.register(self.dispose)

    def _new_manager(self):
        core_id = get_active_core()
        return XrayManager() if core_id == "xray" else AlternativeCoreManager(core_id)

    @property
    def connected(self) -> bool:
        return self._manager.connected

    @property
    def active_core(self) -> str:
        return "xray" if isinstance(self._manager, XrayManager) else self._manager.core_id

    @property
    def local_socks_port(self) -> int:
        if isinstance(self._manager, XrayManager):
            return int(getattr(self._manager, "validation_socks_port", 0) or 0)
        return int(getattr(self._manager, "socks_port", 0) or 0)

    @property
    def startup_verified(self) -> bool:
        if isinstance(self._manager, XrayManager):
            return bool(getattr(self._manager, "startup_verified", False))
        return self.connected

    @property
    def startup_evidence(self) -> str:
        if isinstance(self._manager, XrayManager):
            return str(getattr(self._manager, "startup_evidence", "none"))
        return "core-socks" if self.connected else "none"

    @property
    def route_mode(self) -> str:
        return str(getattr(self._manager, "route_mode", ""))

    @property
    def state(self) -> CoreState:
        if isinstance(self._manager, AlternativeCoreManager):
            return self._manager.state
        return CoreState.CONNECTED if self._manager.connected else CoreState.DISCONNECTED

    @property
    def last_error(self) -> str:
        if isinstance(self._manager, AlternativeCoreManager):
            return self._manager.lifecycle.status.last_error
        return ""

    def start(self, raw_config: str = "", **kwargs) -> None:
        with self._lock:
            selected = get_active_core()
            if selected != self.active_core:
                self._manager.stop()
                self._manager = self._new_manager()
            manager = self._manager
        if isinstance(manager, XrayManager):
            kwargs.pop("core_options", None)
        manager.start(raw_config, **kwargs)

    def reload_selection(self) -> None:
        with self._lock:
            selected = get_active_core()
            if selected != self.active_core:
                self._manager.stop()
                self._manager = self._new_manager()

    def verify_connection(self) -> bool:
        if isinstance(self._manager, XrayManager):
            return self.startup_verified
        verifier = getattr(self._manager, "verify_connection", None)
        return bool(verifier()) if verifier else self.connected

    def connected_ping(self, timeout: float = 1.0) -> int | None:
        return self._manager.connected_ping(timeout)

    def traffic_stats(self) -> tuple[int | None, int | None]:
        return self._manager.traffic_stats()

    def stop(self) -> None:
        with self._lock:
            manager = self._manager
        manager.stop()

    def dispose(self) -> None:
        self.stop()
        PROCESS_REGISTRY.stop_all()