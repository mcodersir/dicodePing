"""Single-active-core connection runtime for desktop builds."""
from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .core_manager import core_dir, get_active_core, resolve_core_path
from .core_runtime import CoreState, LifecycleController, PORT_REGISTRY, PROCESS_REGISTRY
from .diagnostics import get_logger
from .xray import XrayManager

LOGGER = get_logger("connection_manager")


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def register_warp(*, accept_terms: bool) -> Path:
    """Create a local Usque device only after explicit user consent."""
    if not accept_terms:
        raise RuntimeError("Cloudflare terms must be accepted before WARP registration")
    executable = resolve_core_path("warp")
    if executable is None:
        raise RuntimeError("WARP / Usque core is not installed")
    config = core_dir("warp") / "config.json"
    if config.is_file():
        return config
    result = subprocess.run(
        [
            str(executable),
            "--config",
            str(config),
            "register",
            "--accept-tos",
            "--name",
            "dicodePing",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=60,
        cwd=str(executable.parent),
        creationflags=_creation_flags(),
    )
    if result.returncode != 0 or not config.is_file():
        raise RuntimeError((result.stderr or result.stdout or "WARP registration failed")[-1200:])
    return config


def _socks5_connect(port: int, host: str, target_port: int, timeout: float) -> socket.socket:
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
    for host, path in (("www.gstatic.com", "/generate_204"), ("cp.cloudflare.com", "/generate_204")):
        started = time.perf_counter()
        try:
            with _socks5_connect(port, host, 80, timeout) as sock:
                request = (
                    f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                    "Connection: close\r\nUser-Agent: dicodePing/1.8\r\n\r\n"
                ).encode("ascii")
                sock.sendall(request)
                status = sock.recv(128)
                if status.startswith((b"HTTP/1.1 2", b"HTTP/1.0 2", b"HTTP/1.1 3")):
                    return max(1, round((time.perf_counter() - started) * 1000))
        except OSError:
            continue
    return None


class _SystemProxy:
    """Set and restore a desktop SOCKS proxy without leaving stale settings."""

    def __init__(self) -> None:
        self._windows_previous: tuple[int, str] | None = None
        self._gnome_previous: dict[str, str] | None = None

    @staticmethod
    def _value_exists(key, name: str) -> bool:
        try:
            import winreg

            winreg.QueryValueEx(key, name)
            return True
        except OSError:
            return False

    def enable(self, port: int) -> None:
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
        if shutil.which("gsettings"):
            keys = {
                "mode": ("org.gnome.system.proxy", "mode"),
                "host": ("org.gnome.system.proxy.socks", "host"),
                "port": ("org.gnome.system.proxy.socks", "port"),
            }
            self._gnome_previous = {
                name: subprocess.run(
                    ["gsettings", "get", schema, key],
                    capture_output=True,
                    text=True,
                    timeout=3,
                ).stdout.strip()
                for name, (schema, key) in keys.items()
            }
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "host", "127.0.0.1"], check=True)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "port", str(port)], check=True)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"], check=True)

    def restore(self) -> None:
        if os.name == "nt" and self._windows_previous is not None:
            import ctypes
            import winreg

            enabled, server = self._windows_previous
            path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, enabled)
            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
            self._windows_previous = None
        if self._gnome_previous is not None and shutil.which("gsettings"):
            previous = self._gnome_previous
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "host", previous["host"]], check=False)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "port", previous["port"]], check=False)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", previous["mode"]], check=False)
            self._gnome_previous = None


class AlternativeCoreManager:
    def __init__(self, core_id: str) -> None:
        self.core_id = core_id
        self.process: subprocess.Popen[str] | None = None
        self.socks_port = 0
        self._log_handle = None
        self._lock = threading.RLock()
        self._system_proxy = _SystemProxy()
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

    def start(self, _raw_config: str = "", progress: Callable[[str], None] | None = None, **_kwargs) -> None:
        with self._lock:
            self.stop()
            token = self.lifecycle.begin(CoreState.STARTING)
            executable = resolve_core_path(self.core_id)
            if executable is None:
                self.lifecycle.fail(token, f"{self.core_id} core is not downloaded")
                raise RuntimeError(f"{self.core_id} core is not downloaded")
            runtime = core_dir(self.core_id) / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            log_path = runtime / "session.log"
            self._log_handle = log_path.open("w", encoding="utf-8")
            environment = os.environ.copy()
            self.socks_port = PORT_REGISTRY.acquire()
            try:
                command = self._command(executable, runtime, environment)
                if progress:
                    progress(f"Starting {self.core_id}…")
                self.process = PROCESS_REGISTRY.register(
                    subprocess.Popen(
                        command,
                        stdout=self._log_handle,
                        stderr=self._log_handle,
                        stdin=subprocess.DEVNULL,
                        cwd=str(executable.parent),
                        env=environment,
                        text=True,
                        creationflags=_creation_flags(),
                        start_new_session=os.name != "nt",
                    )
                )
                self.lifecycle.transition(token, CoreState.VALIDATING)
                deadline = time.monotonic() + 26
                while time.monotonic() < deadline:
                    token.raise_if_cancelled()
                    if self.process.poll() is not None:
                        tail = log_path.read_text(encoding="utf-8", errors="ignore")[-1600:]
                        raise RuntimeError(f"{self.core_id} stopped during startup: {tail}")
                    if _http_probe_through_socks(self.socks_port, timeout=3.0) is not None:
                        self._system_proxy.enable(self.socks_port)
                        self.lifecycle.transition(token, CoreState.CONNECTED)
                        return
                    token.wait(0.35)
                first_process, self.process = self.process, None
                PROCESS_REGISTRY.stop(first_process, timeout=3)
                if progress:
                    progress(f"Retrying {self.core_id} over HTTP/2…")
                self.process = PROCESS_REGISTRY.register(
                    subprocess.Popen(
                        self._command(executable, runtime, environment, transport="http2"),
                        stdout=self._log_handle,
                        stderr=self._log_handle,
                        stdin=subprocess.DEVNULL,
                        cwd=str(executable.parent),
                        env=environment,
                        text=True,
                        creationflags=_creation_flags(),
                        start_new_session=os.name != "nt",
                    )
                )
                deadline = time.monotonic() + 42
                while time.monotonic() < deadline:
                    token.raise_if_cancelled()
                    if self.process.poll() is not None:
                        break
                    if _http_probe_through_socks(self.socks_port, timeout=3.0) is not None:
                        self._system_proxy.enable(self.socks_port)
                        self.lifecycle.transition(token, CoreState.CONNECTED)
                        return
                    token.wait(0.35)
                tail = log_path.read_text(encoding="utf-8", errors="ignore")[-1800:]
                raise RuntimeError(
                    f"{self.core_id} did not establish verified HTTP traffic via QUIC or HTTP/2: {tail}"
                )
            except Exception as exc:
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
            environment.update(
                {
                    "AETHER_PROTOCOL": "masque",
                    "AETHER_SCAN": "ironclad",
                    "AETHER_QUICK_RECONNECT": "1",
                }
            )
            command = [
                str(executable),
                "--masque",
                "-4",
                "--ironclad",
                "--quick-reconnect",
                "--bind",
                f"127.0.0.1:{self.socks_port}",
            ]
            identity = executable.parent / "aether-masque.toml"
            if identity.is_file():
                command.extend(["--masque-config", str(identity)])
            if transport == "http2":
                command.append("--h2")
            return command
        if self.core_id == "warp":
            config = core_dir("warp") / "config.json"
            if not config.is_file():
                raise RuntimeError("WARP registration is required; activate it from Settings first")
            command = [
                str(executable),
                "--config",
                str(config),
                "socks",
                "-b",
                "127.0.0.1",
                "-p",
                str(self.socks_port),
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
        """Return explicit unsupported values when no core stats API exists."""
        return (None, None)

    def stop(self) -> None:
        with self._lock:
            self.lifecycle.cancel()
            self.lifecycle.status.state = CoreState.STOPPING
            self._teardown()
            self.lifecycle.status.state = CoreState.DISCONNECTED

    def _teardown(self) -> None:
        self._system_proxy.restore()
        process, self.process = self.process, None
        PROCESS_REGISTRY.stop(process, timeout=4)
        if self.socks_port:
            PORT_REGISTRY.release(self.socks_port)
            self.socks_port = 0
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None


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
            self._manager.start(raw_config, **kwargs)

    def reload_selection(self) -> None:
        with self._lock:
            selected = get_active_core()
            if selected != self.active_core:
                self._manager.stop()
                self._manager = self._new_manager()

    def verify_connection(self) -> bool:
        verifier = getattr(self._manager, "verify_connection", None)
        return bool(verifier()) if verifier else self.connected

    def connected_ping(self, timeout: float = 1.0) -> int | None:
        return self._manager.connected_ping(timeout)

    def traffic_stats(self) -> tuple[int | None, int | None]:
        return self._manager.traffic_stats()

    def stop(self) -> None:
        with self._lock:
            self._manager.stop()

    def dispose(self) -> None:
        self.stop()
        PROCESS_REGISTRY.stop_all()
