from __future__ import annotations

import concurrent.futures
import ctypes
import json
import ipaddress
import os
import random
import select
import socket
import struct
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable

from .constants import PING_ATTEMPTS, PING_TIMEOUT

DownloadProgress = Callable[[int, int], None]
MAX_TEXT_DOWNLOAD_BYTES = 16 * 1024 * 1024



def _powershell_route_script(script: str, timeout: float = 15.0) -> subprocess.CompletedProcess[str] | None:
    if os.name != "nt":
        return None
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return None


def install_direct_host_routes(
    ips: Iterable[str],
    tun_name: str = "dicodePing-TUN",
    *,
    only_if_tun: bool = True,
) -> list[str]:
    # Route selected IPv4 hosts outside the active TUN interface. Only routes
    # created here are returned so callers can remove exactly those later.
    if os.name != "nt":
        return []
    valid: list[str] = []
    for value in ips:
        try:
            ip = str(ipaddress.ip_address(str(value).strip()))
            if ":" not in ip and ip not in valid:
                valid.append(ip)
        except ValueError:
            continue
    if not valid:
        return []
    quoted = ",".join("'%s'" % item.replace("'", "''") for item in valid)
    safe_tun = tun_name.replace("'", "''")
    tun_guard = f"$tun = Get-NetAdapter -Name '{safe_tun}' -ErrorAction SilentlyContinue\nif (-not $tun) {{ exit 0 }}" if only_if_tun else ""
    script = f'''
$ErrorActionPreference='SilentlyContinue'
{tun_guard}
$route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
  Where-Object {{ $_.InterfaceAlias -ne '{safe_tun}' -and $_.State -ne 'Invalid' }} |
  Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
if (-not $route) {{ exit 0 }}
$ips = @({quoted})
foreach ($ip in $ips) {{
  $prefix = "$ip/32"
  $existing = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $existing) {{
    if ($route.NextHop -and $route.NextHop -ne '0.0.0.0') {{
      New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $route.InterfaceIndex -NextHop $route.NextHop -RouteMetric 1 -PolicyStore ActiveStore | Out-Null
    }} else {{
      New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $route.InterfaceIndex -RouteMetric 1 -PolicyStore ActiveStore | Out-Null
    }}
    if ($?) {{ Write-Output $ip }}
  }}
}}
'''
    result = _powershell_route_script(script, timeout=20.0)
    if not result:
        return []
    created: list[str] = []
    for line in (result.stdout or "").splitlines():
        value = line.strip()
        try:
            if str(ipaddress.ip_address(value)) == value and ":" not in value:
                created.append(value)
        except ValueError:
            pass
    return created


def remove_direct_host_routes(ips: Iterable[str]) -> None:
    if os.name != "nt":
        return
    valid: list[str] = []
    for value in ips:
        try:
            ip = str(ipaddress.ip_address(str(value).strip()))
            if ":" not in ip and ip not in valid:
                valid.append(ip)
        except ValueError:
            continue
    if not valid:
        return
    quoted = ",".join("'%s'" % item.replace("'", "''") for item in valid)
    script = f'''
$ErrorActionPreference='SilentlyContinue'
$ips = @({quoted})
foreach ($ip in $ips) {{
  Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "$ip/32" -PolicyStore ActiveStore -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false
}}
'''
    _powershell_route_script(script, timeout=15.0)


def fetch_text(url: str, timeout: float = 18.0, progress: DownloadProgress | None = None) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dicodePing/0.1",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json,*/*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    # Subscription hosts can be unavailable to direct DNS on some Windows
    # networks while a user-configured system proxy/PAC can reach them.  The
    # previous code forcibly disabled that path and then reported an opaque
    # getaddrinfo error. Try the OS proxy configuration first, then a direct
    # connection for networks where a stale proxy is configured.
    response = None
    proxy_error: Exception | None = None
    for opener in (urllib.request.build_opener(), urllib.request.build_opener(urllib.request.ProxyHandler({}))):
        try:
            response = opener.open(request, timeout=timeout)
            break
        except Exception as exc:
            proxy_error = exc
    if response is None:
        raise proxy_error or RuntimeError("Unable to open subscription source")
    with response:
        encoding = response.headers.get_content_charset() or "utf-8"
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        if total > MAX_TEXT_DOWNLOAD_BYTES:
            raise RuntimeError("پاسخ منبع بیش از حد بزرگ است")
        chunks: list[bytes] = []
        received = 0
        if progress:
            progress(0, total)
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if received > MAX_TEXT_DOWNLOAD_BYTES:
                raise RuntimeError("پاسخ منبع بیش از حد بزرگ است")
            if progress:
                progress(received, total)
        if progress:
            progress(total or received, total or received or 1)
        return b"".join(chunks).decode(encoding, errors="ignore")


def is_url_reachable(url: str, timeout: float = 8.0) -> bool:
    try:
        fetch_text(url, timeout=timeout)
        return True
    except Exception:
        return False


def is_any_url_reachable(urls: tuple[str, ...] | list[str], timeout: float = 8.0) -> bool:
    for url in urls:
        if is_url_reachable(url, timeout=timeout):
            return True
    return False


def is_any_url_reachable_parallel(
    urls: tuple[str, ...] | list[str],
    timeout: float = 5.0,
    attempts: int = 2,
) -> bool:
    """Race independent connectivity endpoints instead of waiting sequentially."""
    rows = tuple(dict.fromkeys(str(url).strip() for url in urls if str(url).strip()))
    if not rows:
        return False
    for attempt in range(max(1, attempts)):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(rows)))
        futures = [executor.submit(is_url_reachable, url, timeout) for url in rows]
        try:
            for future in concurrent.futures.as_completed(futures, timeout=timeout + 1.0):
                try:
                    if future.result():
                        executor.shutdown(wait=False, cancel_futures=True)
                        return True
                except Exception:
                    continue
        except TimeoutError:
            pass
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if attempt + 1 < attempts:
            time.sleep(0.35 * (attempt + 1))
    return False


def resolve_all_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return []
    result: list[str] = []
    for item in infos:
        if not item or not item[4]:
            continue
        value = str(item[4][0])
        if value and value not in result:
            result.append(value)
    return result


def resolve_all_ipv4(host: str) -> list[str]:
    return [value for value in resolve_all_ips(host) if ":" not in value]


def resolve_ipv4(host: str) -> str:
    addresses = resolve_all_ipv4(host)
    return addresses[0] if addresses else ""


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    value = sum(struct.unpack(f"!{len(data) // 2}H", data))
    value = (value >> 16) + (value & 0xFFFF)
    value += value >> 16
    return (~value) & 0xFFFF


def _icmp_windows(ip: str, timeout: float) -> float | None:
    if os.name != "nt":
        return None
    try:
        iphlpapi = ctypes.WinDLL("iphlpapi.dll")
        ws2_32 = ctypes.WinDLL("ws2_32.dll")
        create = iphlpapi.IcmpCreateFile
        create.restype = ctypes.c_void_p
        close = iphlpapi.IcmpCloseHandle
        close.argtypes = [ctypes.c_void_p]
        send = iphlpapi.IcmpSendEcho
        send.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_ushort,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        send.restype = ctypes.c_uint32
        ws2_32.inet_addr.argtypes = [ctypes.c_char_p]
        ws2_32.inet_addr.restype = ctypes.c_uint32
        destination = ws2_32.inet_addr(ip.encode("ascii"))
        handle = create()
        if not handle or handle == ctypes.c_void_p(-1).value:
            return None
        try:
            payload = b"dicodePing-icmp"
            request = ctypes.create_string_buffer(payload)
            reply = ctypes.create_string_buffer(2048)
            count = send(
                handle,
                destination,
                ctypes.byref(request),
                len(payload),
                None,
                ctypes.byref(reply),
                ctypes.sizeof(reply),
                max(100, int(timeout * 1000)),
            )
            if count <= 0:
                return None
            _address, status, round_trip = struct.unpack_from("=III", reply.raw, 0)
            if status != 0:
                return None
            return float(round_trip)
        finally:
            close(handle)
    except Exception:
        return None


def _icmp_raw(ip: str, timeout: float, sequence: int) -> float | None:
    identifier = (os.getpid() ^ random.randint(1, 0xFFFF)) & 0xFFFF
    payload = struct.pack("!d", time.time()) + b"dicodePing" + bytes(24)
    header = struct.pack("!BBHHH", 8, 0, 0, identifier, sequence)
    packet = struct.pack("!BBHHH", 8, 0, _checksum(header + payload), identifier, sequence) + payload
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
            sock.setblocking(False)
            started = time.perf_counter()
            sock.sendto(packet, (ip, 0))
            deadline = started + timeout
            while time.perf_counter() < deadline:
                remaining = max(0.0, deadline - time.perf_counter())
                readable, _, _ = select.select([sock], [], [], remaining)
                if not readable:
                    return None
                response, _ = sock.recvfrom(2048)
                received = time.perf_counter()
                if len(response) < 28:
                    continue
                ihl = (response[0] & 0x0F) * 4
                if len(response) < ihl + 8:
                    continue
                icmp_type, _code, _sum, reply_id, reply_seq = struct.unpack("!BBHHH", response[ihl : ihl + 8])
                if icmp_type == 0 and reply_id == identifier and reply_seq == sequence:
                    return (received - started) * 1000.0
    except (PermissionError, OSError):
        return None
    return None


def icmp_ping(
    host: str,
    attempts: int = PING_ATTEMPTS,
    timeout: float = PING_TIMEOUT,
    resolved_ip: str = "",
) -> tuple[int | None, str]:
    ip = resolved_ip or resolve_ipv4(host)
    if not ip:
        return None, "dns"
    samples: list[float] = []
    for sequence in range(max(1, attempts)):
        sample = _icmp_windows(ip, timeout) if os.name == "nt" else _icmp_raw(ip, timeout, sequence)
        if sample is not None:
            samples.append(sample)
        if sequence + 1 < attempts:
            time.sleep(0.035)
    if not samples:
        return None, ip
    # Minimum of multiple real Echo replies reduces transient queueing noise.
    return int(round(min(samples))), ip


@dataclass
class PingResult:
    key: str
    ping_ms: int | None
    ip: str


def ping_many(items: Iterable[tuple[str, str]], workers: int = 48, callback: Callable[[int, int], None] | None = None) -> list[PingResult]:
    rows = list(items)
    total = len(rows)
    results: list[PingResult] = []
    done = 0
    resolved_rows = [(key, host, resolve_ipv4(host)) for key, host in rows]
    # When TUN is active, direct /32 routes keep ICMP probes out of the tunnel.
    created_routes = install_direct_host_routes(ip for _, _, ip in resolved_rows if ip)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 96))) as executor:
            futures = {
                executor.submit(icmp_ping, host, PING_ATTEMPTS, PING_TIMEOUT, ip): key
                for key, host, ip in resolved_rows
            }
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    ping_ms, ip = future.result()
                except Exception:
                    ping_ms, ip = None, ""
                results.append(PingResult(key, ping_ms, ip))
                done += 1
                if callback:
                    callback(done, total)
    finally:
        remove_direct_host_routes(created_routes)
    return results


def _parse_ipwho(data: dict) -> dict[str, str]:
    if not data.get("success"):
        return {}
    connection = data.get("connection") or {}
    return {
        "country": str(data.get("country") or ""),
        "country_code": str(data.get("country_code") or "").upper(),
        "region": str(data.get("region") or ""),
        "city": str(data.get("city") or ""),
        "isp": str(connection.get("isp") or connection.get("org") or ""),
        "asn": str(connection.get("asn") or ""),
        "geo_provider": "ipwho.is",
    }


def _parse_ipapi(data: dict) -> dict[str, str]:
    if data.get("error"):
        return {}
    return {
        "country": str(data.get("country_name") or ""),
        "country_code": str(data.get("country_code") or "").upper(),
        "region": str(data.get("region") or ""),
        "city": str(data.get("city") or ""),
        "isp": str(data.get("org") or ""),
        "asn": str(data.get("asn") or ""),
        "geo_provider": "ipapi.co",
    }


def _parse_freeipapi(data: dict) -> dict[str, str]:
    if not isinstance(data, dict) or not data.get("countryCode"):
        return {}
    return {
        "country": str(data.get("countryName") or ""),
        "country_code": str(data.get("countryCode") or "").upper(),
        "region": str(data.get("regionName") or ""),
        "city": str(data.get("cityName") or ""),
        "isp": str(data.get("asnOrganization") or ""),
        "asn": str(data.get("asn") or ""),
        "geo_provider": "freeipapi.com",
    }


def _parse_ip_api(data: dict) -> dict[str, str]:
    if data.get("status") != "success":
        return {}
    return {
        "country": str(data.get("country") or ""),
        "country_code": str(data.get("countryCode") or "").upper(),
        "region": str(data.get("regionName") or ""),
        "city": str(data.get("city") or ""),
        "isp": str(data.get("isp") or data.get("org") or ""),
        "asn": str(data.get("as") or ""),
        "geo_provider": "ip-api.com",
    }



def _parse_ipwhois_app(data: dict) -> dict[str, str]:
    if not isinstance(data, dict) or data.get("success") is False:
        return {}
    code = str(data.get("country_code") or data.get("countryCode") or "").upper()
    if not code:
        return {}
    return {
        "country": str(data.get("country") or ""),
        "country_code": code,
        "region": str(data.get("region") or data.get("region_name") or ""),
        "city": str(data.get("city") or ""),
        "isp": str(data.get("isp") or data.get("org") or ""),
        "asn": str(data.get("asn") or ""),
        "geo_provider": "ipwhois.app",
    }


def lookup_geo(ip: str, timeout: float = 5.5) -> dict[str, str]:
    """Resolve a best-effort network location using provider consensus.

    IP geolocation is inherently approximate. We query multiple independent
    databases concurrently and prefer values confirmed by more than one source.
    """
    if not ip or ip == "dns":
        return {}
    providers = (
        (f"https://ipwho.is/{ip}?fields=success,country,country_code,region,city,connection", _parse_ipwho),
        (f"https://ipapi.co/{ip}/json/", _parse_ipapi),
        (f"https://freeipapi.com/api/json/{ip}", _parse_freeipapi),
        (f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,isp,org,as,query", _parse_ip_api),
        (f"https://ipwhois.app/json/{ip}", _parse_ipwhois_app),
    )

    def query(item):
        url, parser = item
        try:
            return parser(json.loads(fetch_text(url, timeout=timeout)))
        except Exception:
            return {}

    candidates: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as executor:
        for candidate in executor.map(query, providers):
            if candidate and candidate.get("country_code"):
                candidates.append(candidate)
    if not candidates:
        return {}

    def consensus(field: str) -> str:
        values = [str(row.get(field) or "").strip() for row in candidates]
        values = [value for value in values if value]
        if not values:
            return ""
        normalized: dict[str, list[str]] = {}
        for value in values:
            normalized.setdefault(value.casefold(), []).append(value)
        return max(normalized.values(), key=lambda group: (len(group), len(group[0])))[0]

    country_code = consensus("country_code").upper()
    agreeing = [row for row in candidates if str(row.get("country_code") or "").upper() == country_code]
    pool = agreeing or candidates

    def from_pool(field: str) -> str:
        values = [str(row.get(field) or "").strip() for row in pool if row.get(field)]
        if not values:
            return ""
        groups: dict[str, list[str]] = {}
        for value in values:
            groups.setdefault(value.casefold(), []).append(value)
        return max(groups.values(), key=lambda group: (len(group), len(group[0])))[0]

    result = {
        "country": from_pool("country"),
        "country_code": country_code,
        "region": from_pool("region"),
        "city": from_pool("city"),
        "isp": from_pool("isp"),
        "asn": from_pool("asn"),
        "geo_provider": "+".join(sorted({row.get("geo_provider", "") for row in pool if row.get("geo_provider")})),
        "geo_confidence": "multi-provider" if len(agreeing) >= 2 else "single-provider",
    }
    return {key: value for key, value in result.items() if value}
