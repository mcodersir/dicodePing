"""DicodeConfigChecker-compatible Telegram preview crawler.

RC13 keeps network work outside the GUI thread and uses the canonical
``https://t.me/s/<channel>`` preview endpoint exclusively.  It extracts
supported Xray links, deduplicates them, and uses a bounded worker pool.  When
dicodePing exposes a verified local SOCKS5 listener that route is preferred so
DNS and TLS both travel through the bootstrap VPN; the ordinary TUN route is a
same-host fallback.
"""
from __future__ import annotations

import concurrent.futures
import html
import http.client
import json
import random
import re
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .diagnostics import get_logger
from .protocols import parse_endpoint

LOGGER = get_logger("crawler")

CHANNELS_FILE = Path(__file__).resolve().parents[1] / "assets" / "channels.txt"
CANONICAL_CHANNELS_FILE = Path(__file__).resolve().parents[1] / "assets" / "channels.json"
CONFIG_REGEXES = [re.compile(r"\b(?:vmess|vless|trojan|ss)://[^\s<>\"'`\\]+", re.I)]
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_SOCKS_FETCH_SEMAPHORE = threading.BoundedSemaphore(10)
_TELEGRAM_PREVIEW_TEMPLATE = "https://t.me/s/{channel}"


@dataclass
class ChannelResult:
    channel: str
    ok: bool
    found: int
    picked: int
    elapsed_ms: int
    configs: list[str]
    error: str = ""
    bytes_received: int = 0
    transport: str = "direct"


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    name: str
    rank: int


def load_channel_specs(path: Path | None = None) -> list[ChannelSpec]:
    target = path or CANONICAL_CHANNELS_FILE
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        rows = payload.get("channels", [])
    except (OSError, ValueError, TypeError):
        return []
    result: list[ChannelSpec] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        try:
            name = str(row["name"]).strip().strip("/")
            rank = int(row["rank"])
        except (KeyError, TypeError, ValueError):
            continue
        key = name.casefold()
        if not name or rank not in (1, 2) or key in seen:
            continue
        seen.add(key)
        result.append(ChannelSpec(name=name, rank=rank))
    return result


def load_channels(path: Path | None = None) -> list[str]:
    if path is None:
        specs = load_channel_specs()
        if specs:
            return [item.name for item in specs]
    target = path or CHANNELS_FILE
    if not target.exists():
        return []
    channels: list[str] = []
    seen: set[str] = set()
    for raw in target.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
            if line.lower().startswith(prefix):
                line = line[len(prefix) :]
                break
        line = line.strip("/")
        key = line.casefold()
        if not line or key in seen:
            continue
        seen.add(key)
        channels.append(line)
    return channels


def _read_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("truncated SOCKS5 response")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _open_socks5_tunnel(proxy_port: int, host: str, port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", int(proxy_port)), timeout=timeout)
    sock.settimeout(timeout)
    try:
        sock.sendall(b"\x05\x01\x00")
        if _read_exact(sock, 2) != b"\x05\x00":
            raise OSError("SOCKS5 authentication negotiation failed")
        encoded = host.encode("idna")
        if len(encoded) > 255:
            raise OSError("SOCKS5 hostname is too long")
        sock.sendall(b"\x05\x01\x00\x03" + bytes((len(encoded),)) + encoded + struct.pack("!H", port))
        header = _read_exact(sock, 4)
        if header[1] != 0:
            raise OSError(f"SOCKS5 connect failed with status {header[1]}")
        address_type = header[3]
        if address_type == 1:
            _read_exact(sock, 4)
        elif address_type == 4:
            _read_exact(sock, 16)
        elif address_type == 3:
            _read_exact(sock, _read_exact(sock, 1)[0])
        else:
            raise OSError("invalid SOCKS5 address type")
        _read_exact(sock, 2)
        return sock
    except Exception:
        sock.close()
        raise


def _decode_response(data: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type or "", re.I)
    if match:
        charset = match.group(1).strip("\"'")
    return data.decode(charset, errors="ignore")


def _fetch_via_socks(url: str, *, socks_port: int, timeout: float, redirects: int = 2) -> tuple[str, int]:
    """Fetch one URL through the app-owned SOCKS5 listener.

    RC13 uses the app-owned SOCKS5 listener first, including proxy-side DNS.
    The ordinary TUN route is attempted only against the same canonical t.me
    endpoint. Limiting simultaneous TLS handshakes prevents the local Xray
    listener and bootstrap server from being flooded.
    """
    current = url
    with _SOCKS_FETCH_SEMAPHORE:
        for _ in range(max(1, redirects + 1)):
            parsed = urllib.parse.urlsplit(current)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("unsupported Telegram preview URL")
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            raw_sock = _open_socks5_tunnel(socks_port, host, port, timeout)
            conn_sock: socket.socket = raw_sock
            try:
                if parsed.scheme == "https":
                    context = ssl.create_default_context()
                    if hasattr(ssl, "TLSVersion"):
                        context.minimum_version = ssl.TLSVersion.TLSv1_2
                    conn_sock = context.wrap_socket(raw_sock, server_hostname=host)
                    conn_sock.settimeout(timeout)
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) dicodePing-Scanner/1.9\r\n"
                    "Accept: text/html,application/xhtml+xml,text/plain,*/*\r\n"
                    "Accept-Language: en-US,en;q=0.8,fa;q=0.7\r\n"
                    "Accept-Encoding: identity\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii", errors="ignore")
                conn_sock.sendall(request)
                response = http.client.HTTPResponse(conn_sock)
                response.begin()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    response.close()
                    if not location:
                        raise OSError("redirect without Location header")
                    redirected = urllib.parse.urljoin(current, location)
                    if (urllib.parse.urlsplit(redirected).hostname or "").casefold() != "t.me":
                        raise OSError("cross-host Telegram redirect blocked")
                    current = redirected
                    continue
                if response.status < 200 or response.status >= 400:
                    raise OSError(f"HTTP {response.status}")
                data = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(data) > _MAX_RESPONSE_BYTES:
                    raise OSError("Telegram preview response is unexpectedly large")
                return _decode_response(data, response.getheader("Content-Type", "")), len(data)
            finally:
                try:
                    conn_sock.close()
                except OSError:
                    pass
    raise OSError("too many redirects")


class _TMeOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow only redirects that remain on the canonical t.me host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        host = (urllib.parse.urlsplit(newurl).hostname or "").casefold()
        if host != "t.me":
            raise urllib.error.HTTPError(newurl, code, "cross-host Telegram redirect blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_url_payload(url: str, *, timeout: float = 8.0, socks_port: int = 0) -> tuple[str, int, str]:
    if socks_port:
        text, size = _fetch_via_socks(url, socks_port=socks_port, timeout=timeout)
        return text, size, "socks5"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dicodePing-Scanner/1.9",
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.8,fa;q=0.7",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    # Match DicodeConfigChecker: let urllib use the active platform route.
    # The scanner still prefers its explicit SOCKS5 listener when available.
    opener = urllib.request.build_opener(_TMeOnlyRedirectHandler())
    with opener.open(request, timeout=timeout) as response:
        data = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(data) > _MAX_RESPONSE_BYTES:
            raise OSError("Telegram preview response is unexpectedly large")
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="ignore"), len(data), "direct"


def _fetch_url(url: str, *, timeout: float = 8.0, socks_port: int = 0) -> str:
    """Compatibility wrapper used by older tests and callers."""
    return _fetch_url_payload(url, timeout=timeout, socks_port=socks_port)[0]


def _is_usable_preview(page: str) -> bool:
    if not page or not page.strip():
        return False
    lower = page.lower()
    return "tgme_widget_message" in lower or "tgme_channel_info" in lower or bool(extract_configs(page))


def _decode_text(value: str) -> str:
    return html.unescape(value).replace("\\u0026", "&").replace("&amp;", "&")


def _clean_config(value: str) -> str:
    value = _decode_text(value).strip()
    value = re.sub(r"[\u200c\u200f\u202a-\u202e]", "", value)
    while value and re.search(r"[)\]}\"'<>،,.;]+$", value):
        value = value[:-1]
    return value.strip()


def _normalize_key(raw: str) -> str:
    if raw.strip().lower().startswith("vmess://"):
        return raw.strip()
    return raw.strip().split("#", 1)[0]


def extract_configs(page: str) -> list[str]:
    if not page:
        return []
    text = _decode_text(page)
    found: list[str] = []
    seen: set[str] = set()
    for regex in CONFIG_REGEXES:
        for match in regex.findall(text):
            config = _clean_config(match)
            key = _normalize_key(config)
            if not config or key in seen:
                continue
            seen.add(key)
            found.append(config)
    found.reverse()
    return found


def fetch_channel(
    channel: str,
    *,
    per_channel_limit: int = 30,
    timeout: float = 6.5,
    socks_port: int = 0,
    stop_event: threading.Event | None = None,
) -> ChannelResult:
    """Fetch one channel from the canonical t.me preview endpoint only."""
    started = time.monotonic()
    size = 0
    errors: list[str] = []
    routes: list[tuple[str, int]] = []
    if socks_port:
        routes.append(("socks5", int(socks_port)))
    routes.append(("tun", 0))
    url = _TELEGRAM_PREVIEW_TEMPLATE.format(channel=channel)

    for route_name, route_port in routes:
        if stop_event is not None and stop_event.is_set():
            return ChannelResult(
                channel=channel, ok=False, found=0, picked=0,
                elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
                configs=[], error="cancelled", bytes_received=size, transport=route_name,
            )
        try:
            page, received, transport = _fetch_url_payload(
                url, timeout=max(3.0, float(timeout)), socks_port=route_port
            )
            size += received
            if not _is_usable_preview(page):
                raise RuntimeError("t.me returned an unusable preview page")
            configs = extract_configs(page)
            picked = configs[: max(1, int(per_channel_limit))]
            return ChannelResult(
                channel=channel,
                ok=True,
                found=len(configs),
                picked=len(picked),
                elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
                configs=picked,
                bytes_received=size,
                transport=transport if route_name == "socks5" else "tun",
            )
        except Exception as exc:
            compact = str(exc).replace("\n", " ")[-220:]
            errors.append(f"{route_name}:t.me {compact}")

    return ChannelResult(
        channel=channel,
        ok=False,
        found=0,
        picked=0,
        elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
        configs=[],
        error="; ".join(errors[-2:]) or "t.me preview unavailable",
        bytes_received=size,
        transport="adaptive",
    )


def verify_telegram_route(
    channels: list[str],
    *,
    per_channel_limits: dict[str, int] | None = None,
    timeout: float = 10.0,
    socks_port: int = 0,
    stop_event: threading.Event | None = None,
    attempts: int = 3,
) -> ChannelResult:
    """Return the first usable Telegram preview before launching 324 jobs."""
    last = ChannelResult("", False, 0, 0, 1, [], "no channels")
    for channel in channels[: max(1, attempts)]:
        limit = (per_channel_limits or {}).get(channel, 3)
        last = fetch_channel(
            channel,
            per_channel_limit=max(1, int(limit)),
            timeout=timeout,
            socks_port=socks_port,
            stop_event=stop_event,
        )
        if last.ok:
            return last
    return last

def crawl_telegram_channels(
    *,
    channels: list[str] | None = None,
    per_channel_limit: int = 30,
    per_channel_limits: dict[str, int] | None = None,
    max_workers: int = 12,
    timeout: float = 8.0,
    progress: Callable[[int, int, str], None] | None = None,
    result_callback: Callable[[ChannelResult, int, int], None] | None = None,
    stop_event: threading.Event | None = None,
    retry_limit: int = 0,
    socks_port: int = 0,
    max_unique_configs: int | None = None,
    minimum_channels_before_target: int = 0,
) -> list[str]:
    channels = channels if channels is not None else load_channels()
    if not channels:
        return []

    total = len(channels)
    if progress:
        progress(0, total, "")
    raw_configs: list[str] = []
    seen: set[str] = set()
    completed = 0
    worker_count = max(1, min(int(max_workers), total, 16))
    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="dicodePing-telegram",
    )
    queue = iter(channels)
    futures: dict[concurrent.futures.Future[ChannelResult], tuple[str, int]] = {}

    def limit_for(channel: str) -> int:
        if per_channel_limits and channel in per_channel_limits:
            return max(1, int(per_channel_limits[channel]))
        return max(1, int(per_channel_limit))

    def submit(channel: str, attempt: int) -> None:
        future = pool.submit(
            fetch_channel,
            channel,
            per_channel_limit=limit_for(channel),
            timeout=timeout,
            socks_port=socks_port,
            stop_event=stop_event,
        )
        futures[future] = (channel, attempt)

    def fill() -> None:
        while len(futures) < worker_count * 2 and not (stop_event and stop_event.is_set()):
            try:
                submit(next(queue), 0)
            except StopIteration:
                return

    fill()
    cancelled = False
    try:
        while futures:
            if stop_event and stop_event.is_set():
                cancelled = True
                for pending in futures:
                    pending.cancel()
                break
            ready, _ = concurrent.futures.wait(
                tuple(futures), timeout=0.10, return_when=concurrent.futures.FIRST_COMPLETED
            )
            if not ready:
                continue
            for future in ready:
                channel, attempt = futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = ChannelResult(channel, False, 0, 0, 1, [], str(exc))
                if (
                    not result.ok
                    and attempt < max(0, int(retry_limit))
                    and not (stop_event and stop_event.is_set())
                ):
                    submit(channel, attempt + 1)
                    continue
                completed += 1
                if progress:
                    progress(completed, total, channel)
                if result_callback:
                    result_callback(result, completed, total)
                if not result.ok:
                    LOGGER.debug("Crawler: %s failed: %s", channel, result.error)
                    continue
                for raw in result.configs:
                    if not parse_endpoint(raw):
                        continue
                    key = _normalize_key(raw)
                    if key in seen:
                        continue
                    seen.add(key)
                    raw_configs.append(raw)
                target = max(0, int(max_unique_configs or 0))
                if target and completed >= max(0, int(minimum_channels_before_target)) and len(raw_configs) >= target:
                    cancelled = True
                    for pending in futures:
                        pending.cancel()
                    futures.clear()
                    break
            if cancelled:
                break
            fill()
    finally:
        pool.shutdown(wait=True, cancel_futures=cancelled)

    LOGGER.info("Crawler: crawled %d channels, collected %d unique configs", completed, len(raw_configs))
    return raw_configs
