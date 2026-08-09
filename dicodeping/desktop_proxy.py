from __future__ import annotations

"""Cross-platform system-proxy controller for legacy recovery and external cores.

The controller always snapshots the user's previous proxy settings before
changing anything and stores that snapshot under the application runtime
folder.  If an older proxy-mode build or an external core exits unexpectedly, the next
application start can restore the previous settings instead of leaving the
machine behind a dead localhost proxy.
"""

import ctypes
import json
import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .constants import RUNTIME_DIR
from .diagnostics import get_logger

LOGGER = get_logger("desktop_proxy")
PROXY_STATE_FILE = RUNTIME_DIR / "desktop-proxy-state.json"
_LOCAL_BYPASS = "localhost;127.*;10.*;172.16.*;192.168.*;<local>"


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _run(command: list[str], *, timeout: float = 12.0, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        check=check,
        creationflags=_creation_flags(),
    )


def _notify_windows_proxy_changed() -> None:
    try:
        ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
        ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
    except Exception:
        LOGGER.debug("Could not broadcast Windows proxy update", exc_info=True)


def _parse_networksetup(text: str) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().lower()] = value.strip()
    return {
        "enabled": values.get("enabled", "no").lower() == "yes",
        "server": values.get("server", ""),
        "port": values.get("port", "0"),
    }


def _shell_quote(value: str) -> str:
    return shlex.quote(str(value))


class DesktopProxyController:
    def __init__(self, state_path: Path = PROXY_STATE_FILE) -> None:
        self.state_path = state_path
        self.backend = ""
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def _persist_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def enable(self, http_port: int, socks_port: int) -> str:
        http_port = int(http_port)
        socks_port = int(socks_port)
        if not (1 <= http_port <= 65535 and 1 <= socks_port <= 65535):
            raise ValueError("Invalid local proxy port")
        # Recover from a previous interrupted session before taking a new
        # snapshot. Otherwise the dead localhost proxy becomes the new
        # 'previous' state and cannot be repaired automatically.
        if not self.restore_stale():
            raise RuntimeError("Could not restore the previous desktop proxy state")
        system = platform.system().lower()
        if system.startswith("win"):
            state = self._enable_windows(http_port, socks_port)
        elif system == "darwin":
            state = self._enable_macos(http_port, socks_port)
        else:
            state = self._enable_linux(http_port, socks_port)
        self._persist_state(state)
        self.backend = str(state.get("backend") or "")
        self._active = True
        return self.backend

    def restore(self) -> bool:
        """Restore the user's previous proxy state.

        The recovery file is deleted only after a successful restoration. If
        the desktop session is temporarily unavailable during shutdown, the
        next startup can retry instead of permanently leaving localhost as the
        system proxy.
        """
        if not self.state_path.is_file():
            self._active = False
            self.backend = ""
            return True
        restored = False
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._restore_state(state)
            restored = True
        except Exception:
            LOGGER.exception("System proxy restoration failed; recovery state was preserved")
        if restored:
            try:
                self.state_path.unlink(missing_ok=True)
            except Exception:
                LOGGER.debug("Could not remove restored proxy state file", exc_info=True)
        self._active = False
        self.backend = ""
        return restored

    def restore_stale(self) -> bool:
        if not self.state_path.is_file():
            return True
        restored = False
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._restore_state(state)
            restored = True
        except Exception:
            LOGGER.exception("Stale system proxy restoration failed; recovery state was preserved")
        if restored:
            try:
                self.state_path.unlink(missing_ok=True)
            except Exception:
                LOGGER.debug("Could not remove stale proxy state file", exc_info=True)
        return restored

    def _restore_state(self, state: dict[str, Any]) -> None:
        backend = str(state.get("backend") or "")
        if backend == "windows-registry":
            self._restore_windows(state)
        elif backend == "macos-networksetup":
            self._restore_macos(state)
        elif backend == "gnome-gsettings":
            self._restore_gnome(state)
        elif backend == "kde-kioslaverc":
            self._restore_kde(state)
        elif backend == "process-environment":
            self._restore_environment(state)
        else:
            raise RuntimeError(f"Unknown proxy recovery backend: {backend or 'missing'}")

    @staticmethod
    def _reg_read(key: Any, name: str) -> dict[str, Any]:
        import winreg

        try:
            value, value_type = winreg.QueryValueEx(key, name)
            return {"exists": True, "value": value, "type": int(value_type)}
        except OSError:
            return {"exists": False, "value": None, "type": int(winreg.REG_SZ)}

    def _enable_windows(self, http_port: int, socks_port: int) -> dict[str, Any]:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        names = ("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            previous = {name: self._reg_read(key, name) for name in names}
            state = {"backend": "windows-registry", "previous": previous}
            self._persist_state(state)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, (
                f"http=127.0.0.1:{http_port};"
                f"https=127.0.0.1:{http_port};"
                f"socks=127.0.0.1:{socks_port}"
            ))
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, _LOCAL_BYPASS)
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            try:
                winreg.DeleteValue(key, "AutoConfigURL")
            except OSError:
                pass
        _notify_windows_proxy_changed()
        return state

    def _restore_windows(self, state: dict[str, Any]) -> None:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        previous = state.get("previous") if isinstance(state.get("previous"), dict) else {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            for name in ("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL"):
                item = previous.get(name) if isinstance(previous, dict) else None
                if isinstance(item, dict) and item.get("exists"):
                    winreg.SetValueEx(key, name, 0, int(item.get("type") or winreg.REG_SZ), item.get("value"))
                else:
                    try:
                        winreg.DeleteValue(key, name)
                    except OSError:
                        pass
        _notify_windows_proxy_changed()

    @staticmethod
    def _network_services() -> list[str]:
        result = _run(["networksetup", "-listallnetworkservices"], timeout=8.0, check=True)
        rows = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
        enabled = [line for line in rows if not line.startswith("*")]
        selected = enabled or rows
        return [line.lstrip("*").strip() for line in selected if line.lstrip("*").strip()]

    @staticmethod
    def _run_macos_commands(commands: list[list[str]]) -> None:
        if not commands:
            return
        shell = " ; ".join(" ".join(_shell_quote(part) for part in command) for command in commands)
        direct = _run(["/bin/sh", "-c", shell], timeout=45.0)
        if direct.returncode == 0:
            return
        script = f'do shell script {json.dumps(shell)} with administrator privileges'
        elevated = _run(["osascript", "-e", script], timeout=120.0)
        if elevated.returncode != 0:
            detail = (elevated.stderr or elevated.stdout or direct.stderr or direct.stdout).strip()
            raise RuntimeError(detail or "macOS proxy configuration was rejected")

    def _enable_macos(self, http_port: int, socks_port: int) -> dict[str, Any]:
        if not shutil.which("networksetup"):
            raise RuntimeError("networksetup is unavailable")
        services: dict[str, Any] = {}
        commands: list[list[str]] = []
        for service in self._network_services():
            services[service] = {
                "web": _parse_networksetup(_run(["networksetup", "-getwebproxy", service], timeout=8.0).stdout),
                "secure": _parse_networksetup(_run(["networksetup", "-getsecurewebproxy", service], timeout=8.0).stdout),
                "socks": _parse_networksetup(_run(["networksetup", "-getsocksfirewallproxy", service], timeout=8.0).stdout),
                "bypass": [
                    line.strip()
                    for line in _run(["networksetup", "-getproxybypassdomains", service], timeout=8.0).stdout.splitlines()
                    if line.strip() and "aren't any" not in line.lower()
                ],
            }
            commands.extend([
                ["networksetup", "-setwebproxy", service, "127.0.0.1", str(http_port)],
                ["networksetup", "-setwebproxystate", service, "on"],
                ["networksetup", "-setsecurewebproxy", service, "127.0.0.1", str(http_port)],
                ["networksetup", "-setsecurewebproxystate", service, "on"],
                ["networksetup", "-setsocksfirewallproxy", service, "127.0.0.1", str(socks_port)],
                ["networksetup", "-setsocksfirewallproxystate", service, "on"],
                ["networksetup", "-setproxybypassdomains", service, "localhost", "127.0.0.1", "::1"],
            ])
        if not services:
            raise RuntimeError("No macOS network service was found")
        state = {"backend": "macos-networksetup", "services": services}
        self._persist_state(state)
        self._run_macos_commands(commands)
        return state

    def _restore_macos(self, state: dict[str, Any]) -> None:
        services = state.get("services") if isinstance(state.get("services"), dict) else {}
        commands: list[list[str]] = []
        mapping = {
            "web": ("-setwebproxy", "-setwebproxystate"),
            "secure": ("-setsecurewebproxy", "-setsecurewebproxystate"),
            "socks": ("-setsocksfirewallproxy", "-setsocksfirewallproxystate"),
        }
        for service, service_state in services.items():
            if not isinstance(service_state, dict):
                continue
            for key, (setter, state_setter) in mapping.items():
                item = service_state.get(key)
                if not isinstance(item, dict):
                    continue
                server = str(item.get("server") or "127.0.0.1")
                port = str(item.get("port") or "0")
                if port.isdigit() and int(port) > 0:
                    commands.append(["networksetup", setter, str(service), server, port])
                commands.append([
                    "networksetup", state_setter, str(service), "on" if item.get("enabled") else "off"
                ])
            bypass = service_state.get("bypass")
            if isinstance(bypass, list) and bypass:
                commands.append(["networksetup", "-setproxybypassdomains", str(service), *map(str, bypass)])
            else:
                commands.append(["networksetup", "-setproxybypassdomains", str(service), "Empty"])
        self._run_macos_commands(commands)

    @staticmethod
    def _gsettings_get(schema: str, key: str) -> str | None:
        result = _run(["gsettings", "get", schema, key], timeout=5.0)
        return result.stdout.strip() if result.returncode == 0 else None

    @staticmethod
    def _gsettings_set(schema: str, key: str, value: str) -> None:
        result = _run(["gsettings", "set", schema, key, value], timeout=5.0)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or f"gsettings failed: {schema} {key}").strip())

    @staticmethod
    def _notify_kde_proxy_changed() -> None:
        commands = [
            ["qdbus6", "org.kde.kded6", "/kded", "org.kde.kded6.reconfigure"],
            ["qdbus", "org.kde.kded5", "/kded", "org.kde.kded5.reconfigure"],
            [
                "dbus-send", "--session", "--type=signal",
                "/KIO/Scheduler", "org.kde.KIO.Scheduler.reparseSlaveConfiguration",
                "string:''",
            ],
        ]
        for command in commands:
            if shutil.which(command[0]):
                try:
                    _run(command, timeout=5.0)
                except Exception:
                    pass

    def _enable_linux(self, http_port: int, socks_port: int) -> dict[str, Any]:
        if shutil.which("gsettings"):
            keys = [
                ("org.gnome.system.proxy", "mode"),
                ("org.gnome.system.proxy", "use-same-proxy"),
                ("org.gnome.system.proxy", "ignore-hosts"),
                ("org.gnome.system.proxy.http", "host"),
                ("org.gnome.system.proxy.http", "port"),
                ("org.gnome.system.proxy.https", "host"),
                ("org.gnome.system.proxy.https", "port"),
                ("org.gnome.system.proxy.socks", "host"),
                ("org.gnome.system.proxy.socks", "port"),
            ]
            previous = {
                f"{schema}|{key}": value
                for schema, key in keys
                if (value := self._gsettings_get(schema, key)) is not None
            }
            # A machine can have the gsettings executable without a live user
            # D-Bus session (for example sudo/pkexec). Require a readable mode
            # key before selecting this backend.
            if "org.gnome.system.proxy|mode" in previous:
                state = {"backend": "gnome-gsettings", "previous": previous}
                self._persist_state(state)
                self._gsettings_set("org.gnome.system.proxy.http", "host", "'127.0.0.1'")
                self._gsettings_set("org.gnome.system.proxy.http", "port", str(http_port))
                self._gsettings_set("org.gnome.system.proxy.https", "host", "'127.0.0.1'")
                self._gsettings_set("org.gnome.system.proxy.https", "port", str(http_port))
                self._gsettings_set("org.gnome.system.proxy.socks", "host", "'127.0.0.1'")
                self._gsettings_set("org.gnome.system.proxy.socks", "port", str(socks_port))
                if "org.gnome.system.proxy|use-same-proxy" in previous:
                    self._gsettings_set("org.gnome.system.proxy", "use-same-proxy", "false")
                if "org.gnome.system.proxy|ignore-hosts" in previous:
                    self._gsettings_set(
                        "org.gnome.system.proxy",
                        "ignore-hosts",
                        "['localhost', '127.0.0.0/8', '::1']",
                    )
                self._gsettings_set("org.gnome.system.proxy", "mode", "'manual'")
                return state

        writer = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
        reader = shutil.which("kreadconfig6") or shutil.which("kreadconfig5")
        if writer and reader:
            keys = ("ProxyType", "httpProxy", "httpsProxy", "socksProxy", "NoProxyFor", "ReversedException")
            previous: dict[str, dict[str, Any]] = {}
            for key in keys:
                result = _run([reader, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", key], timeout=5.0)
                previous[key] = {"value": result.stdout.rstrip("\n"), "exists": result.returncode == 0 and bool(result.stdout)}
            state = {"backend": "kde-kioslaverc", "writer": Path(writer).name, "previous": previous}
            self._persist_state(state)
            values = {
                "ProxyType": "1",
                "httpProxy": f"http://127.0.0.1:{http_port}",
                "httpsProxy": f"http://127.0.0.1:{http_port}",
                "socksProxy": f"socks://127.0.0.1:{socks_port}",
                "NoProxyFor": "localhost,127.0.0.1,::1",
                "ReversedException": "false",
            }
            for key, value in values.items():
                result = _run([writer, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", key, value], timeout=5.0)
                if result.returncode != 0:
                    raise RuntimeError((result.stderr or result.stdout or "KDE proxy update failed").strip())
            self._notify_kde_proxy_changed()
            return state

        return self._enable_environment(http_port, socks_port)

    def _restore_gnome(self, state: dict[str, Any]) -> None:
        previous = state.get("previous") if isinstance(state.get("previous"), dict) else {}
        for packed, value in previous.items():
            if "|" not in packed:
                continue
            schema, key = packed.split("|", 1)
            try:
                self._gsettings_set(schema, key, str(value))
            except Exception:
                LOGGER.debug("Could not restore gsettings key %s", packed, exc_info=True)

    def _restore_kde(self, state: dict[str, Any]) -> None:
        writer = shutil.which(str(state.get("writer") or "")) or shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
        if not writer:
            return
        previous = state.get("previous") if isinstance(state.get("previous"), dict) else {}
        for key, item in previous.items():
            if not isinstance(item, dict):
                continue
            command = [writer, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", str(key)]
            if item.get("exists"):
                command.append(str(item.get("value") or ""))
            else:
                command.append("")
            _run(command, timeout=5.0)
        self._notify_kde_proxy_changed()

    def _enable_environment(self, http_port: int, socks_port: int) -> dict[str, Any]:
        names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")
        previous = {name: {"exists": name in os.environ, "value": os.environ.get(name, "")} for name in names}
        state = {"backend": "process-environment", "previous": previous}
        self._persist_state(state)
        values = {
            "HTTP_PROXY": f"http://127.0.0.1:{http_port}",
            "HTTPS_PROXY": f"http://127.0.0.1:{http_port}",
            "ALL_PROXY": f"socks5h://127.0.0.1:{socks_port}",
            "NO_PROXY": "localhost,127.0.0.1,::1",
        }
        for key, value in values.items():
            os.environ[key] = value
            os.environ[key.lower()] = value
        return state

    @staticmethod
    def _restore_environment(state: dict[str, Any]) -> None:
        previous = state.get("previous") if isinstance(state.get("previous"), dict) else {}
        for name, item in previous.items():
            if isinstance(item, dict) and item.get("exists"):
                os.environ[str(name)] = str(item.get("value") or "")
            else:
                os.environ.pop(str(name), None)


def restore_stale_system_proxy() -> None:
    DesktopProxyController().restore_stale()
