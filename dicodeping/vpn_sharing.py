"""Recoverable VPN sharing for Windows ICS and Linux NAT/AP."""
from __future__ import annotations

import atexit
import base64
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .constants import DATA_DIR
from .diagnostics import get_logger

LOGGER = get_logger("vpn_sharing")
STATE_FILE = DATA_DIR / "vpn-sharing-state.json"
RUNTIME_DIR = DATA_DIR / "sharing"


@dataclass(frozen=True, slots=True)
class SharingState:
    usb_enabled: bool
    hotspot_enabled: bool
    tun_interface: str
    error: str = ""


_lock = threading.RLock()
_hostapd_process: subprocess.Popen | None = None
_dnsmasq_process: subprocess.Popen | None = None


def _run(command: list[str], *, timeout: float = 12, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(f"{command[0]}: {detail[-700:]}")
    return result


def _powershell(script: str) -> str:
    result = _run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=25,
    )
    return result.stdout.strip()


def _enable_windows(tun_name: str, usb: bool, hotspot: bool) -> dict:
    # HNetCfg.HNetShare is the COM automation facade for INetSharingManager.
    # 0 = public/upstream (the dicodePing TUN), 1 = private/downstream.
    patterns: list[str] = []
    if usb:
        patterns += ["USB", "RNDIS", "Remote NDIS"]
    if hotspot:
        patterns += ["Local Area Connection*", "Wi-Fi Direct", "Mobile Hotspot"]
    pattern_b64 = base64.b64encode(json.dumps(patterns).encode("utf-8")).decode("ascii")
    script = rf"""
$ErrorActionPreference = 'Stop'
$manager = New-Object -ComObject HNetCfg.HNetShare
$connections = @($manager.EnumEveryConnection())
$rows = foreach ($connection in $connections) {{
  $props = $manager.NetConnectionProps($connection)
  [pscustomobject]@{{ Connection=$connection; Name=[string]$props.Name; Device=[string]$props.DeviceName }}
}}
$public = $rows | Where-Object {{ $_.Name -eq {json.dumps(tun_name)} -or $_.Device -eq {json.dumps(tun_name)} }} | Select-Object -First 1
if (-not $public) {{ throw 'dicodePing TUN adapter was not found by ICS' }}
$patterns = ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{pattern_b64}')))
$private = $rows | Where-Object {{
  $row = $_
  ($patterns | Where-Object {{ $row.Name -like "*$_*" -or $row.Device -like "*$_*" }}).Count -gt 0
}} | Select-Object -First 1
if (-not $private) {{ throw 'USB tether or Mobile Hotspot adapter was not found' }}
foreach ($row in $rows) {{
  $cfg = $manager.INetSharingConfigurationForINetConnection($row.Connection)
  if ($cfg.SharingEnabled -and ($row.Name -eq $public.Name -or $row.Name -eq $private.Name)) {{ $cfg.DisableSharing() }}
}}
$manager.INetSharingConfigurationForINetConnection($public.Connection).EnableSharing(0)
$manager.INetSharingConfigurationForINetConnection($private.Connection).EnableSharing(1)
[pscustomobject]@{{ public=$public.Name; private=$private.Name }} | ConvertTo-Json -Compress
"""
    return json.loads(_powershell(script))


def _disable_windows(state: dict) -> None:
    names_b64 = base64.b64encode(
        json.dumps([state.get("public", ""), state.get("private", "")]).encode("utf-8")
    ).decode("ascii")
    script = rf"""
$ErrorActionPreference = 'Stop'
$names = ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{names_b64}')))
$manager = New-Object -ComObject HNetCfg.HNetShare
foreach ($connection in @($manager.EnumEveryConnection())) {{
  $props = $manager.NetConnectionProps($connection)
  if ($names -contains [string]$props.Name) {{
    $cfg = $manager.INetSharingConfigurationForINetConnection($connection)
    if ($cfg.SharingEnabled) {{ $cfg.DisableSharing() }}
  }}
}}
"""
    _powershell(script)


def _interfaces() -> list[str]:
    root = Path("/sys/class/net")
    return [path.name for path in root.iterdir()] if root.is_dir() else []


def _wireless_interfaces() -> list[str]:
    return [name for name in _interfaces() if Path(f"/sys/class/net/{name}/wireless").exists()]


def _pick_usb_interface() -> str | None:
    candidates = [
        name for name in _interfaces()
        if re.match(r"^(usb|rndis|enx)[a-zA-Z0-9_.-]*$", name)
    ]
    return candidates[0] if candidates else None


def _iptables(rule: list[str], *, delete: bool = False) -> None:
    table: list[str] = []
    body = list(rule)
    if body[:2] == ["-t", "nat"]:
        table, body = body[:2], body[2:]
    action = body[0]
    specification = body[1:]
    if delete:
        _run(["iptables", *table, "-D", *specification], check=False)
        return
    check = _run(["iptables", *table, "-C", *specification], check=False)
    if check.returncode:
        _run(["iptables", *table, action, *specification])


def _start_linux_hotspot(interface: str) -> dict:
    global _hostapd_process, _dnsmasq_process
    if not shutil.which("hostapd"):
        raise RuntimeError("hostapd is required for Wi-Fi hotspot sharing")
    if not shutil.which("dnsmasq"):
        raise RuntimeError("dnsmasq is required for hotspot DHCP")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    hostapd_config = RUNTIME_DIR / "hostapd.conf"
    dnsmasq_config = RUNTIME_DIR / "dnsmasq.conf"
    hostapd_config.write_text(
        "\n".join(
            [
                f"interface={interface}",
                "driver=nl80211",
                "ssid=dicodePing",
                "hw_mode=g",
                "channel=6",
                "wmm_enabled=1",
                "auth_algs=1",
                "wpa=2",
                "wpa_passphrase=dicodePing18",
                "wpa_key_mgmt=WPA-PSK",
                "rsn_pairwise=CCMP",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    dnsmasq_config.write_text(
        "\n".join(
            [
                f"interface={interface}",
                "bind-interfaces",
                "dhcp-range=192.168.88.20,192.168.88.200,255.255.255.0,12h",
                "dhcp-option=3,192.168.88.1",
                "dhcp-option=6,1.1.1.1,8.8.8.8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _run(["ip", "link", "set", interface, "down"])
    _run(["ip", "addr", "flush", "dev", interface])
    _run(["ip", "addr", "add", "192.168.88.1/24", "dev", interface])
    _run(["ip", "link", "set", interface, "up"])
    _hostapd_process = subprocess.Popen(
        ["hostapd", str(hostapd_config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _dnsmasq_process = subprocess.Popen(
        ["dnsmasq", "--no-daemon", f"--conf-file={dnsmasq_config}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"interface": interface, "address": "192.168.88.1/24"}


def _enable_linux(tun_name: str, usb: bool, hotspot: bool) -> dict:
    previous_forward = Path("/proc/sys/net/ipv4/ip_forward").read_text().strip()
    downstream: list[str] = []
    state: dict = {"previous_forward": previous_forward, "interfaces": downstream}
    try:
        Path("/proc/sys/net/ipv4/ip_forward").write_text("1\n")
        if usb:
            interface = _pick_usb_interface()
            if not interface:
                raise RuntimeError("no USB/RNDIS tether interface was detected")
            _run(["ip", "addr", "replace", "192.168.89.1/24", "dev", interface])
            _run(["ip", "link", "set", interface, "up"])
            downstream.append(interface)
        if hotspot:
            wireless = _wireless_interfaces()
            if not wireless:
                raise RuntimeError("no Wi-Fi interface with AP capability was detected")
            state["hotspot"] = _start_linux_hotspot(wireless[0])
            downstream.append(wireless[0])
        if not downstream:
            raise RuntimeError("no downstream sharing interface is active")
        for interface in downstream:
            _iptables(["-A", "FORWARD", "-i", interface, "-o", tun_name, "-j", "ACCEPT"])
            _iptables(
                [
                    "-A", "FORWARD", "-i", tun_name, "-o", interface,
                    "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT",
                ]
            )
        _iptables(["-t", "nat", "-A", "POSTROUTING", "-o", tun_name, "-j", "MASQUERADE"])
        return state
    except Exception:
        _disable_linux(tun_name, state)
        raise


def _stop_process(process: subprocess.Popen | None) -> None:
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def _disable_linux(tun_name: str, state: dict) -> None:
    global _hostapd_process, _dnsmasq_process
    for interface in state.get("interfaces", []):
        _iptables(["-A", "FORWARD", "-i", interface, "-o", tun_name, "-j", "ACCEPT"], delete=True)
        _iptables(
            [
                "-A", "FORWARD", "-i", tun_name, "-o", interface,
                "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT",
            ],
            delete=True,
        )
    _iptables(["-t", "nat", "-A", "POSTROUTING", "-o", tun_name, "-j", "MASQUERADE"], delete=True)
    _stop_process(_dnsmasq_process)
    _stop_process(_hostapd_process)
    _dnsmasq_process = _hostapd_process = None
    previous = str(state.get("previous_forward", "0"))
    if previous in {"0", "1"}:
        Path("/proc/sys/net/ipv4/ip_forward").write_text(previous + "\n")


def enable_sharing(tun_name: str, *, usb: bool, hotspot: bool) -> str:
    if not usb and not hotspot:
        return ""
    if not tun_name:
        return "TUN interface is missing"
    with _lock:
        try:
            disable_sharing(tun_name)
            if os.name == "nt":
                platform_state = _enable_windows(tun_name, usb, hotspot)
            elif os.name == "posix" and Path("/proc/sys/net/ipv4/ip_forward").exists():
                platform_state = _enable_linux(tun_name, usb, hotspot)
            else:
                return "VPN sharing is not supported on this platform"
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps(
                    {
                        "tun": tun_name,
                        "usb": usb,
                        "hotspot": hotspot,
                        "platform": "windows" if os.name == "nt" else "linux",
                        "state": platform_state,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return ""
        except Exception as exc:
            LOGGER.exception("Could not enable VPN sharing")
            return str(exc)


def disable_sharing(tun_name: str = "") -> str:
    with _lock:
        if not STATE_FILE.is_file():
            return ""
        try:
            saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            active_tun = str(saved.get("tun") or tun_name)
            if saved.get("platform") == "windows":
                _disable_windows(saved.get("state") or {})
            elif saved.get("platform") == "linux":
                _disable_linux(active_tun, saved.get("state") or {})
            STATE_FILE.unlink(missing_ok=True)
            return ""
        except Exception as exc:
            LOGGER.exception("Could not disable VPN sharing")
            return str(exc)


def get_sharing_state(tun_name: str) -> SharingState:
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return SharingState(
            bool(saved.get("usb")),
            bool(saved.get("hotspot")),
            str(saved.get("tun") or tun_name),
        )
    except Exception:
        return SharingState(False, False, tun_name)


atexit.register(disable_sharing)
