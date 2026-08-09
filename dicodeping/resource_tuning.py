"""Adaptive resource limits for the dicodePing runtime.

The scanner runs on machines ranging from small routers to desktop
workstations.  Keeping these limits in one immutable profile prevents each
subsystem from guessing its own (usually excessive) concurrency.
"""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from functools import lru_cache


def _physical_memory_bytes() -> int:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except (AttributeError, OSError):
            pass
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return max(0, pages * page_size)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    cpu_count: int
    memory_bytes: int
    crawl_workers: int
    probe_workers: int
    retry_workers: int
    ping_workers: int
    dns_workers: int
    internal_queue_limit: int
    network_buffer_kib: int
    mode: str = "optimized"

    @property
    def memory_mib(self) -> int:
        return self.memory_bytes // (1024 * 1024)


def build_resource_profile(
    cpu_count: int | None = None,
    memory_bytes: int | None = None,
    mode: str = "optimized",
) -> ResourceProfile:
    cpu = max(1, int(cpu_count or os.cpu_count() or 1))
    memory = max(0, int(_physical_memory_bytes() if memory_bytes is None else memory_bytes))
    gib = memory / (1024**3) if memory else 4.0

    if gib <= 1.0:
        crawl, probe, ping, dns, buffer_kib = 2, 4, 8, 4, 64
    elif gib <= 2.0:
        crawl, probe, ping, dns, buffer_kib = 3, 8, 12, 6, 128
    elif gib <= 4.0:
        crawl, probe, ping, dns, buffer_kib = 4, 16, 24, 12, 256
    else:
        crawl = min(10, max(4, cpu * 2))
        probe = min(48, max(12, cpu * 4))
        ping = min(64, max(16, cpu * 6))
        dns = min(32, max(8, cpu * 3))
        buffer_kib = 512 if gib < 12 else 1024

    # CPU remains the final guard on low-power boards with deceptively large RAM.
    crawl = min(crawl, max(2, cpu * 2))
    probe = min(probe, max(4, cpu * 4))
    ping = min(ping, max(8, cpu * 6))
    dns = min(dns, max(4, cpu * 3))
    retry = max(2, min(12, probe // 3))
    normalized_mode = "professional" if str(mode).lower() == "professional" else "optimized"
    if normalized_mode == "professional":
        crawl = min(18, max(crawl + 2, round(crawl * 1.45)))
        probe = min(64, max(probe + 4, round(probe * 1.50)))
        ping = min(96, max(ping + 8, round(ping * 1.45)))
        dns = min(48, max(dns + 4, round(dns * 1.40)))
        retry = min(16, max(retry + 2, round(retry * 1.40)))
        buffer_kib = min(2048, max(512, buffer_kib * 2))
    queue_limit = max(probe, min(256 if normalized_mode == "professional" else 192, probe * 3))
    return ResourceProfile(
        cpu_count=cpu,
        memory_bytes=memory,
        crawl_workers=crawl,
        probe_workers=probe,
        retry_workers=retry,
        ping_workers=ping,
        dns_workers=dns,
        internal_queue_limit=queue_limit,
        network_buffer_kib=buffer_kib,
        mode=normalized_mode,
    )


@lru_cache(maxsize=2)
def current_resource_profile(mode: str = "optimized") -> ResourceProfile:
    return build_resource_profile(mode=mode)


def resource_mode_from_settings(settings: dict | None) -> str:
    value = str((settings or {}).get("resource_mode") or "optimized").lower()
    return "professional" if value == "professional" else "optimized"
