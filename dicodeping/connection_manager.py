"""Single-active-core connection runtime for desktop builds."""
from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable

from .core_manager import core_dir, get_active_core, resolve_core_path
from .diagnostics import get_logger
from .xray import XrayManager

LOGGER = get_logger("connection_manager")


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _socks5_connect(port: int, host: str, target_port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.settimeout(timeout)
    sock.sendall(b"\x05\x01\x00")
    if sock.recv(2) != b"\x05\x00":
        sock.close()
        raise OSError("SOCKS5 authentication negotiation failed")
    encoded = host.encode("idna")
    if len(encoded) > 255:
        sock.close()
        raise OSError("SOCKS5 hostname is too long")
    sock.sendall(b"\x05\x01\x00\x03" + bytes((len(encoded),)) + encoded + struct.pack("!H", target_port))
    header = sock.recv(4)
    if len(header) != 4 or header[1] != 0:
        sock.close()
        raise OSError("SOCKS5 connection was rejected")
    address_type = header[3]
    if address_type == 1:
        remaining = 4
    elif address_type == 4:
        remaining = 16
    elif address_type == 3:
        length = sock.recv(1)
        if not length:
            sock.close()
            raise OSError("invalid SOCKS5 response")
        remaining = length[0]
    else:
        sock.close()
        raise OSError("invalid SOCKS5 address type")
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            sock.close()
            raise OSError("truncated SOCKS5 response")
        remaining -= len(chunk)
    if len(sock.recv(2)) != 2:
        sock.close()
        raise OSError("truncated SOCKS5 port")
    return sock


def _http_probe_through_socks(port: int, timeout: float = 5.0) -> int | None:
    for host, path in (
        ("www.gstatic.com", "/generate_204"),
        ("cp.cloudflare.com", "/generate_204"),
    ):
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

    @staticmethod
    def _value_exists(key, name: str) -> bool:
        try:
            import winreg
            winreg.QueryValueEx(key, name)
            return True
        except OSError:
            return False

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
        self.socks_port = 1819
        self._log_handle = None
        self._lock = threading.RLock()
        self._system_proxy = _SystemProxy()

    @property
    def connected(self) -> bool:
        return bool(self.process and self.process.poll() is None and self.connected_ping(0.8) is not None)

    def start(self, _raw_config: str = "", progress: Callable[[str], None] | None = None, **_kwargs) -> None:
        self.stop()
        executable = resolve_core_path(self.core_id)
        if executable is None:
            raise RuntimeError(f"{self.core_id} core is not downloaded")
        runtime = core_dir(self.core_id) / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        log_path = runtime / "session.log"
        self._log_handle = log_path.open("w", encoding="utf-8")

        if self.core_id == "aether":
            command = [
                str(executable),
                "--masque",
                "--ironclad",
                "--quick-reconnect",
                "--log-level",
                "info",
            ]
            environment = os.environ.copy()
            environment.update(
                {
                    "AETHER_PROTOCOL": "masque",
                    "AETHER_SCAN": "ironclad",
                    "AETHER_QUICK_RECONNECT": "1",
                    "AETHER_LOG_LEVEL": "info",
                }
            )
        elif self.core_id == "psiphon":
            config = core_dir("psiphon") / "client.config"
            if not config.is_file():
                raise RuntimeError(
                    "Psiphon requires a signed distribution client.config. "
                    "Install the Shirokhorshid companion on Android or provide an authorized config."
                )
            self.socks_port = int(json.loads(config.read_text(encoding="utf-8")).get("LocalSocksProxyPort") or 1819)
            command = [
                str(executable),
                "-config",
                str(config),
                "-dataRootDirectory",
                str(runtime),
            ]
            environment = os.environ.copy()
        else:
            raise RuntimeError(f"unsupported alternative core: {self.core_id}")

        if progress:
            progress(f"Starting {self.core_id}…")
        self.process = subprocess.Popen(
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
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                tail = log_path.read_text(encoding="utf-8", errors="ignore")[-1600:]
                self.stop()
                raise RuntimeError(f"{self.core_id} stopped during startup: {tail}")
            if _http_probe_through_socks(self.socks_port, timeout=3.0) is not None:
                self._system_proxy.enable(self.socks_port)
                return
            time.sleep(0.35)
        self.stop()
        raise RuntimeError(f"{self.core_id} did not establish a verified tunnel")

    def verify_connection(self) -> bool:
        return self.connected_ping(3.5) is not None

    def connected_ping(self, timeout: float = 1.0) -> int | None:
        if not self.process or self.process.poll() is not None:
            return None
        return _http_probe_through_socks(self.socks_port, timeout=max(0.4, timeout))

    def traffic_stats(self) -> tuple[int, int]:
        return 0, 0

    def stop(self) -> None:
        with self._lock:
            self._system_proxy.restore()
            process, self.process = self.process, None
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if self._log_handle:
                self._log_handle.close()
                self._log_handle = None


class ConnectionManager:
    """Stable facade that guarantees exactly one active core."""

    def __init__(self) -> None:
        self._manager: XrayManager | AlternativeCoreManager = self._new_manager()

    def _new_manager(self):
        core_id = get_active_core()
        return XrayManager() if core_id == "xray" else AlternativeCoreManager(core_id)

    @property
    def connected(self) -> bool:
        return self._manager.connected

    @property
    def active_core(self) -> str:
        return "xray" if isinstance(self._manager, XrayManager) else self._manager.core_id

    def start(self, raw_config: str = "", **kwargs) -> None:
        selected = get_active_core()
        if selected != self.active_core:
            self._manager.stop()
            self._manager = self._new_manager()
        self._manager.start(raw_config, **kwargs)

    def reload_selection(self) -> None:
        selected = get_active_core()
        if selected != self.active_core:
            self._manager.stop()
            self._manager = self._new_manager()

    def verify_connection(self) -> bool:
        verifier = getattr(self._manager, "verify_connection", None)
        return bool(verifier()) if verifier else self.connected

    def connected_ping(self, timeout: float = 1.0) -> int | None:
        return self._manager.connected_ping(timeout)

    def traffic_stats(self) -> tuple[int, int]:
        return self._manager.traffic_stats()

    def stop(self) -> None:
        self._manager.stop()
