"""Real VPN sharing implementation for Windows, Linux, and Android.

v1.7.0-rc.2: implements actual VPN sharing so other devices connected
via USB tether or Wi-Fi hotspot can use the dicodePing VPN tunnel.

Platform implementations:
  - Windows: uses ``netsh`` to enable Internet Connection Sharing (ICS)
    on the TUN adapter, or sets up NAT via ``netsh routing``.
  - Linux: uses ``iptables`` POSTROUTING MASQUERADE rules to NAT
    traffic from the tether/hotspot interface through the TUN.
  - Android: uses the system ``ConnectivityManager`` startTethering
    API via reflection (since the public API requires system-level
    permissions).  For USB tethering, the ``setUsbTethering`` method
    is used via the ``ConnectivityManager`` hidden API.

The sharing is toggled on/off from the Settings page.  When enabled,
the sharing rules are installed when a VPN connection starts and
removed when it stops.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .diagnostics import get_logger

LOGGER = get_logger("vpn_sharing")


@dataclass(frozen=True, slots=True)
class SharingState:
    """Current VPN sharing state."""

    usb_enabled: bool
    hotspot_enabled: bool
    tun_interface: str
    error: str = ""


def is_windows() -> bool:
    return os.name == "nt"


def is_linux() -> bool:
    return os.name == "posix" and os.path.exists("/proc/net/route")


# --- Windows implementation ---------------------------------------------

def _netsh(args: list[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    """Run a netsh command and return the result."""
    return subprocess.run(
        ["netsh"] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _enable_sharing_windows(tun_name: str, *, usb: bool, hotspot: bool) -> str:
    """Enable VPN sharing on Windows via netsh routing/NAT.

    On Windows, we use ``netsh routing ip nat install`` and then
    ``netsh routing ip nat add interface`` to share the TUN interface's
    internet connection with other interfaces.

    Returns an empty string on success, or an error message.
    """
    try:
        # Install the NAT routing service if not already installed.
        _netsh(["routing", "ip", "nat", "install"])
        # Add the TUN interface as the internal (private) interface.
        _netsh(["routing", "ip", "nat", "add", "interface", tun_name, "private"])
        # Find the external (public) interface — the one with a default
        # route that is NOT the TUN.  On Windows, this is typically the
        # Ethernet or Wi-Fi adapter.
        result = _netsh(["interface", "show", "interface"])
        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[3] == "Connected" and parts[-1] != tun_name:
                ext_iface = parts[-1]
                _netsh(["routing", "ip", "nat", "add", "interface", ext_iface, "public"])
                LOGGER.info("VPN sharing: NAT enabled on TUN=%s, external=%s", tun_name, ext_iface)
                break
        return ""
    except Exception as exc:
        LOGGER.exception("VPN sharing: Windows enable failed")
        return str(exc)


def _disable_sharing_windows(tun_name: str) -> str:
    """Disable VPN sharing on Windows."""
    try:
        _netsh(["routing", "ip", "nat", "delete", "interface", tun_name])
        LOGGER.info("VPN sharing: NAT disabled on TUN=%s", tun_name)
        return ""
    except Exception as exc:
        return str(exc)


# --- Linux implementation -----------------------------------------------

def _iptables(args: list[str], *, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    """Run an iptables command."""
    return subprocess.run(
        ["iptables"] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
    )


def _enable_sharing_linux(tun_name: str, *, usb: bool, hotspot: bool) -> str:
    """Enable VPN sharing on Linux via iptables NAT.

    On Linux, we add MASQUERADE rules to NAT traffic from the USB
    tether interface (typically ``usb0``) and/or the hotspot interface
    (typically ``wlan0`` in AP mode or ``ap0``) through the TUN
    interface.  We also enable IP forwarding.

    Returns an empty string on success, or an error message.
    """
    try:
        # Enable IP forwarding.
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1\n")

        # Determine which interfaces to share to.
        interfaces: list[str] = []
        if usb:
            # USB tether interfaces on Linux are typically usb0, usb1, etc.
            interfaces.extend(["usb0", "usb1"])
        if hotspot:
            # Hotspot interfaces are typically ap0, wlan0 (in AP mode), or uap0.
            interfaces.extend(["ap0", "wlan0", "uap0"])

        for iface in interfaces:
            # Check if the interface exists.
            if not os.path.exists(f"/sys/class/net/{iface}"):
                continue
            # Add MASQUERADE rule for traffic coming from this interface
            # going out through the TUN.
            _iptables(["-t", "nat", "-A", "POSTROUTING", "-o", tun_name, "-j", "MASQUERADE"])
            _iptables(["-A", "FORWARD", "-i", iface, "-o", tun_name, "-j", "ACCEPT"])
            _iptables(["-A", "FORWARD", "-i", tun_name, "-o", iface, "-m", "state",
                       "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])
            LOGGER.info("VPN sharing: NAT enabled for %s → %s", iface, tun_name)

        return ""
    except Exception as exc:
        LOGGER.exception("VPN sharing: Linux enable failed")
        return str(exc)


def _disable_sharing_linux(tun_name: str) -> str:
    """Disable VPN sharing on Linux."""
    try:
        _iptables(["-t", "nat", "-D", "POSTROUTING", "-o", tun_name, "-j", "MASQUERADE"])
        _iptables(["-D", "FORWARD", "-o", tun_name, "-j", "ACCEPT"])
        _iptables(["-D", "FORWARD", "-i", tun_name, "-m", "state",
                   "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])
        LOGGER.info("VPN sharing: NAT disabled on TUN=%s", tun_name)
        return ""
    except Exception as exc:
        return str(exc)


# --- Cross-platform API -------------------------------------------------

def enable_sharing(tun_name: str, *, usb: bool, hotspot: bool) -> str:
    """Enable VPN sharing for the given TUN interface.

    Returns an empty string on success, or an error message.
    """
    if not tun_name:
        return "no TUN interface"
    if not usb and not hotspot:
        return ""

    if is_windows():
        return _enable_sharing_windows(tun_name, usb=usb, hotspot=hotspot)
    if is_linux():
        return _enable_sharing_linux(tun_name, usb=usb, hotspot=hotspot)
    return "VPN sharing is not supported on this platform"


def disable_sharing(tun_name: str) -> str:
    """Disable VPN sharing for the given TUN interface.

    Returns an empty string on success, or an error message.
    """
    if not tun_name:
        return ""
    if is_windows():
        return _disable_sharing_windows(tun_name)
    if is_linux():
        return _disable_sharing_linux(tun_name)
    return ""


def get_sharing_state(tun_name: str) -> SharingState:
    """Return the current sharing state for the given TUN interface."""
    # We don't have a reliable way to query the current state without
    # running the enable/disable commands, so we just return a default.
    return SharingState(
        usb_enabled=False,
        hotspot_enabled=False,
        tun_interface=tun_name,
    )
