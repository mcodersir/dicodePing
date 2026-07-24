"""Real ICMP ping implementation for Windows and Linux.

The previous implementation used TCP connect to measure latency, which
does not reflect the actual network round-trip time.  This module uses
the system ``ping`` command (which sends real ICMP Echo Request packets)
to measure latency, with a raw-socket fallback for environments where
``ping`` is not available.

On Windows, the system ``ping`` command is used with ``-n`` (count) and
``-w`` (timeout in ms).  On Linux, ``ping`` is used with ``-c`` (count),
``-W`` (timeout in seconds), and ``-q`` (quiet).

The raw-socket fallback creates a proper ICMP Echo Request packet,
sends it via a raw socket, and waits for the ICMP Echo Reply.  This
requires root/administrator privileges on most systems, so it is only
used when the system ``ping`` command is not available.
"""
from __future__ import annotations

import os
import re
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable

from .diagnostics import get_logger

LOGGER = get_logger("icmp_ping")


@dataclass(frozen=True, slots=True)
class PingResult:
    """Result of an ICMP ping measurement."""

    host: str
    ok: bool
    ping_ms: int | None
    samples_ms: tuple[int, ...]
    error: str | None = None

    @property
    def jitter_ms(self) -> float:
        """Standard deviation of the samples, as a simple jitter measure."""
        if len(self.samples_ms) < 2:
            return 0.0
        avg = sum(self.samples_ms) / len(self.samples_ms)
        variance = sum((s - avg) ** 2 for s in self.samples_ms) / len(self.samples_ms)
        return variance ** 0.5

    @property
    def packet_loss_percent(self) -> int:
        """Always 0 for ok results; 100 for failed results."""
        return 0 if self.ok else 100


def _is_windows() -> bool:
    return os.name == "nt"


def _system_ping(host: str, *, count: int = 3, timeout_ms: int = 1500) -> PingResult:
    """Use the system ``ping`` command to send real ICMP Echo Requests."""
    if _is_windows():
        args = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    else:
        timeout_s = max(1, timeout_ms // 1000)
        args = ["ping", "-c", str(count), "-W", str(timeout_s), "-q", host]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=count * (timeout_ms / 1000.0) + 5.0,
            creationflags=subprocess.CREATE_NO_WINDOW if _is_windows() else 0,
        )
    except FileNotFoundError:
        # ping command not found
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="ping command not found")
    except subprocess.TimeoutExpired:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="ping timed out")
    except Exception as exc:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error=str(exc))

    output = (result.stdout or "") + (result.stderr or "")

    # Parse the output for individual ping times.
    # Windows: "Reply from X: time=12ms" or "Reply from X: time=2ms"
    # Linux:   "rtt min/avg/max/mdev = 1.234/2.345/3.456/0.567 ms"
    #          or "64 bytes from X: icmp_seq=1 ttl=64 time=2.34 ms"
    samples: list[int] = []

    # Windows format: time=12ms
    for m in re.finditer(r"time[=<](\d+)\s*ms", output, re.IGNORECASE):
        samples.append(int(m.group(1)))

    # Linux format: time=2.34 ms (float)
    if not samples:
        for m in re.finditer(r"time[=<]([\d.]+)\s*ms", output, re.IGNORECASE):
            try:
                samples.append(int(float(m.group(1))))
            except ValueError:
                pass

    # Linux summary: rtt min/avg/max/mdev = 1.234/2.345/3.456/0.567 ms
    if not samples:
        m = re.search(r"rtt\s+min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output)
        if m:
            try:
                avg = float(m.group(2))
                samples.append(int(avg))
            except ValueError:
                pass

    if not samples:
        # Check for 100% packet loss
        if "100% packet loss" in output or "100% loss" in output or "Destination Host Unreachable" in output:
            return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="100% packet loss")
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error=f"could not parse ping output: {output[:200]}")

    avg_ping = sum(samples) // len(samples)
    return PingResult(host=host, ok=True, ping_ms=avg_ping, samples_ms=tuple(samples))


def _raw_icmp_ping(host: str, *, count: int = 3, timeout_ms: int = 1500) -> PingResult:
    """Send real ICMP Echo Request packets via a raw socket.

    Requires root/administrator privileges.  Used as a fallback when the
    system ``ping`` command is not available.
    """
    try:
        dest_addr = socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
    except socket.gaierror:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="DNS resolution failed")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    except PermissionError:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="raw socket requires root")
    except Exception as exc:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error=str(exc))

    samples: list[int] = []
    try:
        sock.settimeout(timeout_ms / 1000.0)
        for seq in range(count):
            # Build ICMP Echo Request header.
            icmp_type = 8  # Echo Request
            icmp_code = 0
            icmp_checksum = 0
            icmp_id = os.getpid() & 0xFFFF
            icmp_seq = seq + 1
            header = struct.pack("!BBHHH", icmp_type, icmp_code, icmp_checksum, icmp_id, icmp_seq)
            data = b"dicodePing" + struct.pack("!d", time.time())
            # Calculate checksum.
            checksum = _icmp_checksum(header + data)
            header = struct.pack("!BBHHH", icmp_type, icmp_code, checksum, icmp_id, icmp_seq)
            packet = header + data

            started = time.perf_counter()
            try:
                sock.sendto(packet, (dest_addr, 0))
                while True:
                    try:
                        recv_packet, _ = sock.recvfrom(1024)
                    except socket.timeout:
                        break
                    # Parse the IP header to find the ICMP header.
                    if len(recv_packet) < 28:
                        continue
                    ip_header_len = (recv_packet[0] & 0x0F) * 4
                    if len(recv_packet) < ip_header_len + 8:
                        continue
                    icmp_header = recv_packet[ip_header_len:ip_header_len + 8]
                    recv_type, recv_code, recv_checksum, recv_id, recv_seq = struct.unpack("!BBHHH", icmp_header)
                    if recv_type == 0 and recv_id == icmp_id and recv_seq == icmp_seq:
                        elapsed = (time.perf_counter() - started) * 1000
                        samples.append(max(1, int(elapsed)))
                        break
            except Exception:
                pass
    finally:
        sock.close()

    if not samples:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="no ICMP replies received")

    avg_ping = sum(samples) // len(samples)
    return PingResult(host=host, ok=True, ping_ms=avg_ping, samples_ms=tuple(samples))


def _icmp_checksum(data: bytes) -> int:
    """Calculate the ICMP checksum for the given data."""
    if len(data) % 2:
        data += b"\x00"
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def icmp_ping(host: str, *, count: int = 3, timeout_ms: int = 1500) -> PingResult:
    """Send real ICMP Echo Request packets to ``host`` and measure latency.

    Tries the system ``ping`` command first (which is available on all
    modern Windows and Linux systems).  Falls back to a raw-socket
    implementation if ``ping`` is not found.
    """
    if not host:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="empty host")

    # Try system ping first.
    result = _system_ping(host, count=count, timeout_ms=timeout_ms)
    if result.ok or result.error != "ping command not found":
        return result

    # Fall back to raw socket.
    LOGGER.debug("system ping not found, falling back to raw ICMP socket for %s", host)
    return _raw_icmp_ping(host, count=count, timeout_ms=timeout_ms)


def icmp_ping_many(
    hosts: Iterable[str],
    *,
    count: int = 3,
    timeout_ms: int = 1500,
    workers: int = 64,
) -> dict[str, PingResult]:
    """Ping many hosts in parallel using real ICMP.

    Returns a ``{host: PingResult}`` dict.  This is the function that
    the service layer should call instead of the old TCP-connect ping.
    """
    import concurrent.futures

    host_list = list(dict.fromkeys(h for h in hosts if h))
    if not host_list:
        return {}

    results: dict[str, PingResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(host_list) or 1)) as pool:
        future_to_host = {pool.submit(icmp_ping, h, count=count, timeout_ms=timeout_ms): h for h in host_list}
        for future in concurrent.futures.as_completed(future_to_host):
            host = future_to_host[future]
            try:
                results[host] = future.result()
            except Exception as exc:
                results[host] = PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error=str(exc))
    return results
