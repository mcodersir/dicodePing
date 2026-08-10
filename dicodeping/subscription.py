from __future__ import annotations

import base64
import concurrent.futures
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import certifi

from .constants import CACHE_DIR, DEFAULT_SUBSCRIPTION_MIRRORS
from .models import SourceDefinition

ProgressCallback = Callable[[int, int], None]


@dataclass(slots=True)
class SubscriptionPayload:
    source: SourceDefinition
    content: str
    from_cache: bool = False


def _cache_path(source: SourceDefinition) -> Path:
    safe = "".join(c for c in source.id if c.isalnum() or c in "-_") or "source"
    return CACHE_DIR / "subscriptions-v3" / f"{safe}.txt"


def _decode_github_contents(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return text
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict) and payload.get("encoding") == "base64" and isinstance(payload.get("content"), str):
            return base64.b64decode("".join(payload["content"].split())).decode("utf-8", errors="replace")
    except Exception:
        return text
    return text


def _download(url: str, progress: ProgressCallback | None = None) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "dicodePing/3",
            "Accept": "text/plain, application/json;q=0.8, */*;q=0.2",
            "Cache-Control": "no-cache",
        },
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        total = int(response.headers.get("Content-Length") or 0)
        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if received > 16 * 1024 * 1024:
                raise RuntimeError("subscription is larger than 16 MiB")
            if progress:
                progress(received, total)
        raw = b"".join(chunks)
    return _decode_github_contents(raw.decode("utf-8-sig", errors="replace"))


def fetch_subscription(source: SourceDefinition, progress: ProgressCallback | None = None) -> SubscriptionPayload:
    candidates = DEFAULT_SUBSCRIPTION_MIRRORS if source.is_default or source.id == "default" else (source.url,)
    candidates = tuple(dict.fromkeys(url for url in candidates if url))
    errors: list[str] = []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(candidates) or 1))
    futures = {pool.submit(_download, url, progress): url for url in candidates}
    try:
        for future in concurrent.futures.as_completed(futures):
            try:
                content = future.result()
                if not content.strip():
                    raise RuntimeError("empty subscription")
            except Exception as exc:
                errors.append(f"{futures[future]}: {exc}")
                continue
            for pending in futures:
                if pending is not future:
                    pending.cancel()
            path = _cache_path(source)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return SubscriptionPayload(source, content, False)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    try:
        content = _cache_path(source).read_text(encoding="utf-8")
        if content.strip():
            return SubscriptionPayload(source, content, True)
    except OSError:
        pass
    raise RuntimeError("; ".join(errors[-3:]) or "subscription download failed")
