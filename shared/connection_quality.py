"""Reliable endpoint and proxy-path health measurements.

ICMP latency is intentionally not used for automatic selection. A server can answer
ICMP while its proxy credentials, TLS, transport, routing, or remote egress are broken.
The final signal is an authenticated HTTP request through the running local SOCKS5
endpoint. All operations are bounded by deadlines and return structured failures.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median, pstdev
import ipaddress
import socket
import ssl
import time
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    latency_ms: float | None
    stage: str
    error: str | None = None
    samples_ms: tuple[float, ...] = ()

    @property
    def jitter_ms(self) -> float:
        return float(pstdev(self.samples_ms)) if len(self.samples_ms) > 1 else 0.0


def tcp_connect_probe(host: str, port: int, *, timeout: float = 1.5, attempts: int = 2) -> ProbeResult:
    if not host or not (1 <= int(port) <= 65535):
        return ProbeResult(False, None, 'tcp', 'invalid host or port')
    values: list[float] = []
    last_error: str | None = None
    for _ in range(max(1, attempts)):
        started = time.perf_counter()
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                values.append((time.perf_counter() - started) * 1000.0)
        except OSError as exc:
            last_error = f'{type(exc).__name__}: {exc}'
    if not values:
        return ProbeResult(False, None, 'tcp', last_error)
    return ProbeResult(True, float(median(values)), 'tcp', samples_ms=tuple(values))


def _read_exact(sock: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError('unexpected EOF from SOCKS5 proxy')
        data.extend(chunk)
    return bytes(data)


def _socks5_connect(sock: socket.socket, host: str, port: int) -> None:
    sock.sendall(b'\x05\x01\x00')
    if _read_exact(sock, 2) != b'\x05\x00':
        raise ConnectionError('SOCKS5 proxy rejected no-auth negotiation')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        encoded = host.encode('idna')
        if len(encoded) > 255:
            raise ValueError('target hostname is too long')
        address = b'\x03' + bytes([len(encoded)]) + encoded
    else:
        address = (b'\x01' + ip.packed) if ip.version == 4 else (b'\x04' + ip.packed)
    sock.sendall(b'\x05\x01\x00' + address + int(port).to_bytes(2, 'big'))
    head = _read_exact(sock, 4)
    if head[0] != 5 or head[1] != 0:
        raise ConnectionError(f'SOCKS5 connect failed with code {head[1]}')
    atyp = head[3]
    if atyp == 1:
        _read_exact(sock, 4)
    elif atyp == 4:
        _read_exact(sock, 16)
    elif atyp == 3:
        _read_exact(sock, _read_exact(sock, 1)[0])
    else:
        raise ConnectionError('invalid SOCKS5 address type')
    _read_exact(sock, 2)


def socks5_https_probe(
    proxy_host: str,
    proxy_port: int,
    *,
    url: str = 'https://www.gstatic.com/generate_204',
    timeout: float = 6.0,
    attempts: int = 2,
) -> ProbeResult:
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname:
        return ProbeResult(False, None, 'proxy-http', 'probe URL must be HTTPS')
    target_host = parts.hostname
    target_port = parts.port or 443
    path = parts.path or '/'
    if parts.query:
        path += '?' + parts.query
    values: list[float] = []
    last_error: str | None = None
    context = ssl.create_default_context()
    for _ in range(max(1, attempts)):
        started = time.perf_counter()
        try:
            with socket.create_connection((proxy_host, int(proxy_port)), timeout=timeout) as raw:
                raw.settimeout(timeout)
                _socks5_connect(raw, target_host, target_port)
                with context.wrap_socket(raw, server_hostname=target_host) as tls:
                    request = (
                        f'GET {path} HTTP/1.1\r\nHost: {target_host}\r\n'
                        'User-Agent: dicodePing-HealthProbe/1\r\n'
                        'Connection: close\r\n\r\n'
                    ).encode('ascii')
                    tls.sendall(request)
                    status_line = b''
                    while b'\r\n' not in status_line and len(status_line) < 4096:
                        chunk = tls.recv(256)
                        if not chunk:
                            break
                        status_line += chunk
                    first = status_line.split(b'\r\n', 1)[0]
                    fields = first.split()
                    if len(fields) < 2 or fields[1] not in {b'200', b'204'}:
                        raise ConnectionError(f'unexpected HTTP status: {first[:120]!r}')
            values.append((time.perf_counter() - started) * 1000.0)
        except (OSError, ssl.SSLError, ValueError, ConnectionError) as exc:
            last_error = f'{type(exc).__name__}: {exc}'
    if not values:
        return ProbeResult(False, None, 'proxy-http', last_error)
    return ProbeResult(True, float(median(values)), 'proxy-http', samples_ms=tuple(values))


def choose_best(results: Iterable[tuple[str, ProbeResult]]) -> str | None:
    """Return the best successful candidate using median latency plus jitter penalty."""
    valid = [(key, result) for key, result in results if result.ok and result.latency_ms is not None]
    if not valid:
        return None
    return min(valid, key=lambda item: (item[1].latency_ms + item[1].jitter_ms * 0.35, item[0]))[0]


def validate_then_choose(
    candidates: Sequence[str],
    probe: Callable[[str], ProbeResult],
) -> tuple[str | None, dict[str, ProbeResult]]:
    measured = {candidate: probe(candidate) for candidate in candidates}
    return choose_best(measured.items()), measured
