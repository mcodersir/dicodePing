"""Real ICMP ping implementation for Windows and Linux.

v1.7.0-rc.3: simplified to use a single fast system ping call with a
short timeout.  The previous version tried to send multiple ICMP Echo
Requests and took too long, causing pings to appear as >1000ms.

The system ``ping`` command is the most reliable way to send real ICMP
packets on both Windows and Linux without requiring root privileges.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Iterable

from .diagnostics import get_logger

LOGGER = get_logger("icmp_ping")


@dataclass(frozen=True, slots=True)
class PingResult:
    host: str
    ok: bool
    ping_ms: int | None
    samples_ms: tuple[int, ...]
    error: str | None = None

    @property
    def jitter_ms(self) -> float:
        if len(self.samples_ms) < 2:
            return 0.0
        avg = sum(self.samples_ms) / len(self.samples_ms)
        variance = sum((s - avg) ** 2 for s in self.samples_ms) / len(self.samples_ms)
        return variance ** 0.5


def _is_windows() -> bool:
    return os.name == "nt"


def icmp_ping(host: str, *, count: int = 1, timeout_ms: int = 2000) -> PingResult:
    """Send real ICMP Echo Request(s) via the system ``ping`` command.

    Args:
        host: IP address or hostname to ping.
        count: Number of ICMP Echo Requests to send (default 1 for speed).
        timeout_ms: Per-reply timeout in milliseconds (default 2000).

    Returns:
        PingResult with the average latency and all samples.
    """
    if not host:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="empty host")

    count = max(1, min(count, 4))
    # Use a short total timeout so unreachable hosts don't block the
    # whole batch.  Total = count * timeout + 2s buffer.
    total_timeout = count * (timeout_ms / 1000.0) + 2.0

    if _is_windows():
        args = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    else:
        timeout_s = max(1, timeout_ms // 1000)
        args = ["ping", "-c", str(count), "-W", str(timeout_s), host]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=total_timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if _is_windows() else 0,
        )
    except FileNotFoundError:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="ping not found")
    except subprocess.TimeoutExpired:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="timeout")
    except Exception as exc:
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error=str(exc))

    output = (result.stdout or "") + (result.stderr or "")
    samples: list[int] = []

    # Windows: "time=12ms" or "time<1ms"
    for m in re.finditer(r"time[=<](\d+)\s*ms", output, re.IGNORECASE):
        samples.append(int(m.group(1)))

    # Linux: "time=2.34 ms" (float)
    if not samples:
        for m in re.finditer(r"time[=<]([\d.]+)\s*ms", output, re.IGNORECASE):
            try:
                samples.append(int(float(m.group(1))))
            except ValueError:
                pass

    # Linux summary: rtt min/avg/max/mdev
    if not samples:
        m = re.search(r"rtt\s+min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output)
        if m:
            try:
                samples.append(int(float(m.group(2))))
            except ValueError:
                pass

    if not samples:
        if "100%" in output or "Unreachable" in output or "timed out" in output.lower():
            return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="no reply")
        return PingResult(host=host, ok=False, ping_ms=None, samples_ms=(), error="parse failed")

    avg = sum(samples) // len(samples)
    return PingResult(host=host, ok=True, ping_ms=avg, samples_ms=tuple(samples))


def icmp_ping_many(
    hosts: Iterable[str],
    *,
    count: int = 1,
    timeout_ms: int = 2000,
    workers: int = 64,
) -> dict[str, PingResult]:
    """Ping many hosts in parallel using real ICMP."""
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
