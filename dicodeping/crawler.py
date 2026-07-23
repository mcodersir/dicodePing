"""Telegram channel crawler for the dicodePing scanner.

This module mirrors the "stage 1" logic of DicodeConfigChecker
(https://github.com/mcodersir/DicodeConfigChecker) but is intentionally
simpler:

* No two-stage disconnect-then-test flow.  The scanner crawls Telegram
  previews using the **program's own already-running VPN**, so the user's
  network is already able to reach t.me.
* No per-channel configuration UI.  The list of channels lives in
  ``assets/channels.txt`` and is shipped with the build.
* No reporting files.  The crawler returns a flat list of raw config
  URIs that the scanner then probes.

The crawler is exposed as a single function, ``crawl_telegram_channels``,
which the scanner calls from a background worker thread.
"""
from __future__ import annotations

import concurrent.futures
import html
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .diagnostics import get_logger
from .protocols import parse_endpoint

LOGGER = get_logger("crawler")

# --- Channel list --------------------------------------------------------

CHANNELS_FILE = Path(__file__).resolve().parents[1] / "assets" / "channels.txt"

# Regexes used to extract config URIs from the Telegram preview HTML.
# These match the patterns used by DicodeConfigChecker, but we only keep
# the proxy-style protocols that dicodePing can actually probe through
# xray (vmess / vless / trojan / ss / ssr).  Telegram MTProto and SOCKS
# links are ignored because dicodePing does not run a Telegram tunnel.
CONFIG_REGEXES = [
    re.compile(r"\b(?:vmess|vless|trojan|ss|ssr|snell)://[^\s<>\"'`\\]+", re.I),
    re.compile(r"\b(?:hysteria2|hy2|tuic)://[^\s<>\"'`\\]+", re.I),
]


@dataclass
class ChannelResult:
    """Result of fetching a single Telegram channel."""

    channel: str
    ok: bool
    found: int
    picked: int
    elapsed_ms: int
    configs: list[str]
    error: str = ""


def load_channels(path: Path | None = None) -> list[str]:
    """Return the curated list of Telegram channels.

    Lines that start with ``#`` or are blank are skipped.  The leading
    ``t.me/`` (if any) is stripped so the value is just the channel
    username.
    """
    target = path or CHANNELS_FILE
    if not target.exists():
        return []
    channels: list[str] = []
    seen: set[str] = set()
    for raw in target.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Allow both "ChannelName" and "t.me/ChannelName" forms.
        if line.lower().startswith("t.me/"):
            line = line[5:]
        if line.lower().startswith("https://t.me/"):
            line = line[len("https://t.me/") :]
        line = line.strip("/")
        if not line or line.lower() in seen:
            continue
        seen.add(line.lower())
        channels.append(line)
    return channels


# --- HTTP fetch ----------------------------------------------------------

def _fetch_url(url: str, *, timeout: float = 12.0) -> str:
    """Fetch a URL with a browser-like UA and return its text body."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "dicodePing-Scanner/1.6"
            ),
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.8,fa;q=0.7",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="ignore")


def _is_usable_preview(page: str) -> bool:
    """Reject generic/block pages returned as HTTP 200 by a broken route."""
    if not page or not page.strip():
        return False
    lower = page.lower()
    return (
        "tgme_widget_message" in lower
        or "tgme_channel_info" in lower
        or bool(extract_configs(page))
    )


def _decode_text(s: str) -> str:
    s = html.unescape(s)
    s = s.replace("\\u0026", "&")
    s = s.replace("&amp;", "&")
    return s


def _clean_config(s: str) -> str:
    s = _decode_text(s).strip()
    s = re.sub(r"[\u200c\u200f\u202a-\u202e]", "", s)
    # Trim trailing punctuation that Telegram's preview HTML sometimes
    # leaves attached to the URI.
    while s and re.search(r"[)\]}\"'<>،,.;]+$", s):
        s = s[:-1]
    return s.strip()


def _normalize_key(raw: str) -> str:
    """Return a stable dedup key for a config URI.

    For vmess, the entire URI is kept (its JSON body is canonicalised by
    the protocols module later).  For everything else we drop the remark
    (#name) so two configs that differ only by display name are treated
    as the same.
    """
    lower = raw.strip().lower()
    if lower.startswith("vmess://"):
        return raw.strip()
    return raw.strip().split("#", 1)[0]


def extract_configs(page: str) -> list[str]:
    """Extract unique config URIs from a Telegram preview page.

    Order is preserved (newest first, matching the Telegram widget order
    after we reverse).
    """
    if not page:
        return []
    text = _decode_text(page)
    found: list[str] = []
    seen: set[str] = set()
    for regex in CONFIG_REGEXES:
        for match in regex.findall(text):
            cfg = _clean_config(match)
            if not cfg:
                continue
            key = _normalize_key(cfg)
            if key in seen:
                continue
            seen.add(key)
            found.append(cfg)
    found.reverse()
    return found


def fetch_channel(channel: str, *, per_channel_limit: int = 30, timeout: float = 12.0) -> ChannelResult:
    """Fetch a single Telegram channel's preview page and extract configs.

    Tries ``t.me`` first and falls back to ``telegram.me`` if the primary
    host returns an unusable page (mirrors DicodeConfigChecker).
    """
    import time

    started = time.monotonic()
    try:
        try:
            page = _fetch_url(f"https://t.me/s/{channel}", timeout=timeout)
            if not _is_usable_preview(page):
                raise RuntimeError("t.me returned an unusable preview page")
        except Exception as primary_error:
            try:
                page = _fetch_url(f"https://telegram.me/s/{channel}", timeout=timeout)
                if not _is_usable_preview(page):
                    raise RuntimeError("telegram.me returned an unusable preview page")
            except Exception as fallback_error:
                raise RuntimeError(
                    f"t.me unavailable ({primary_error}); telegram.me also failed ({fallback_error})"
                ) from fallback_error
        configs = extract_configs(page)
        picked = configs[:per_channel_limit]
        return ChannelResult(
            channel=channel,
            ok=True,
            found=len(configs),
            picked=len(picked),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            configs=picked,
        )
    except Exception as exc:
        return ChannelResult(
            channel=channel,
            ok=False,
            found=0,
            picked=0,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            configs=[],
            error=str(exc),
        )


def crawl_telegram_channels(
    *,
    channels: list[str] | None = None,
    per_channel_limit: int = 30,
    max_workers: int = 8,
    timeout: float = 12.0,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[str]:
    """Crawl every channel in parallel and return a flat, deduped config list.

    Args:
        channels: The list of channel usernames to fetch.  If ``None``,
            the bundled ``assets/channels.txt`` is loaded.
        per_channel_limit: Maximum number of configs to keep per channel.
            Telegram preview pages show the most recent ~20 posts, so
            anything above 30 has no effect in practice.
        max_workers: Parallel HTTP fetches.  Eight is a safe default that
            does not trigger Telegram's rate limiter.
        timeout: Per-request timeout, in seconds.
        progress: Optional callback ``(done, total, channel)`` called
            after each channel completes.

    Returns:
        A list of unique, valid config URIs (vmess/vless/trojan/ss/ssr).
        Configs that cannot be parsed by the protocols module are dropped.
    """
    channels = channels if channels is not None else load_channels()
    if not channels:
        return []

    total = len(channels)
    if progress:
        progress(0, total, "")

    raw_configs: list[str] = []
    seen: set[str] = set()
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_channel, channel, per_channel_limit=per_channel_limit, timeout=timeout): channel
            for channel in channels
        }
        for future in concurrent.futures.as_completed(futures):
            channel = futures[future]
            try:
                result: ChannelResult = future.result()
            except Exception as exc:
                LOGGER.debug("Crawler: channel %s raised %s", channel, exc)
                result = ChannelResult(channel=channel, ok=False, found=0, picked=0, elapsed_ms=0, configs=[], error=str(exc))
            completed += 1
            if progress:
                progress(completed, total, channel)
            if not result.ok:
                LOGGER.debug("Crawler: %s failed: %s", channel, result.error)
                continue
            for raw in result.configs:
                # Keep only configs that the protocols module can parse
                # (drops malformed URIs and unsupported protocols).
                if not parse_endpoint(raw):
                    continue
                key = _normalize_key(raw)
                if key in seen:
                    continue
                seen.add(key)
                raw_configs.append(raw)

    LOGGER.info(
        "Crawler: crawled %d channels, collected %d unique configs",
        total, len(raw_configs),
    )
    return raw_configs
