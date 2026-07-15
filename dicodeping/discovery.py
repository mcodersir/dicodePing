from __future__ import annotations

import concurrent.futures
import base64
import json
import threading
from pathlib import Path
from typing import Callable

from .constants import ASSET_DIR, CACHE_DIR, DEFAULT_SUBSCRIPTION_MIRRORS, DEFAULT_SUBSCRIPTION_URL, MAX_DISCOVERY_CONFIGS
from .i18n import tr
from .models import DiscoveredConfig, SourceDefinition
from .net import fetch_text
from .protocols import decode_subscription, normalize_key, parse_endpoint
from .sources import source_id_for_url

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]
BUNDLED_DEFAULT_SUBSCRIPTION = ASSET_DIR / "default-subscription.txt"


def normalize_subscription_urls(custom_urls: list[str] | tuple[str, ...] | None = None) -> list[str]:
    rows = [DEFAULT_SUBSCRIPTION_URL]
    for raw in custom_urls or []:
        url = str(raw or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        if url not in rows:
            rows.append(url)
    return rows


def _subscription_cache_path(source: SourceDefinition) -> Path:
    safe_id = "".join(char for char in source.id if char.isalnum() or char in ("-", "_")) or "source"
    return CACHE_DIR / "subscriptions" / f"{safe_id}.txt"


def _decode_download_payload(text: str) -> str:
    """Decode GitHub Contents API responses while preserving normal subscriptions."""
    value = text.lstrip()
    if not value.startswith("{"):
        return text
    try:
        payload = json.loads(value)
        encoded = payload.get("content") if isinstance(payload, dict) else None
        if payload.get("encoding") == "base64" and isinstance(encoded, str):
            return base64.b64decode("".join(encoded.split())).decode("utf-8", errors="ignore")
    except (ValueError, TypeError):
        pass
    return text


def _usable_download(url: str, progress: Callable[[int, int], None] | None) -> tuple[str, list[str]]:
    text = _decode_download_payload(fetch_text(url, timeout=12, progress=progress))
    rows = [raw for raw in decode_subscription(text) if parse_endpoint(raw)]
    if not rows:
        raise RuntimeError("source returned no usable configs")
    return text, rows


def _fetch_subscription(source: SourceDefinition, progress: Callable[[int, int], None] | None = None) -> list[str]:
    candidates = (DEFAULT_SUBSCRIPTION_MIRRORS if source.is_default or source.id == "default" else (source.url,))
    errors: list[str] = []
    urls = tuple(dict.fromkeys(candidates))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(urls)))
    futures = {executor.submit(_usable_download, url, progress): url for url in urls}
    try:
        for future in concurrent.futures.as_completed(futures):
            try:
                text, rows = future.result()
            except Exception as exc:
                errors.append(f"{futures[future]}: {exc}")
                continue
            for pending in futures:
                if pending is not future:
                    pending.cancel()
            path = _subscription_cache_path(source)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return rows
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    # A previously verified subscription is safer than replacing a live list
    # with nothing when DNS or a temporary CDN outage occurs.
    try:
        cached = _subscription_cache_path(source).read_text(encoding="utf-8")
        rows = [raw for raw in decode_subscription(cached) if parse_endpoint(raw)]
        if rows:
            return rows
    except OSError:
        pass
    if source.is_default or source.id == "default":
        try:
            bundled = BUNDLED_DEFAULT_SUBSCRIPTION.read_text(encoding="utf-8")
            rows = [raw for raw in decode_subscription(bundled) if parse_endpoint(raw)]
            if rows:
                return rows
        except OSError:
            pass
    raise RuntimeError("; ".join(errors[-2:]) or "subscription download failed")


def discover_config_entries(
    sources: list[SourceDefinition],
    stage: StageCallback | None = None,
    progress: ProgressCallback | None = None,
    language: str = "fa",
) -> list[DiscoveredConfig]:
    enabled = [source for source in sorted(sources, key=lambda item: item.order) if source.enabled]
    if not enabled:
        raise RuntimeError(tr(language, "source_fetch_failed"))
    if stage:
        stage(tr(language, "getting_sources"))

    found: list[DiscoveredConfig] = []
    seen: set[str] = set()
    errors: list[str] = []
    state_lock = threading.Lock()
    byte_state: dict[str, tuple[int, int, bool]] = {source.id: (0, 0, False) for source in enabled}

    def report(source_id: str, current: int, total: int, finished: bool = False) -> None:
        with state_lock:
            byte_state[source_id] = (max(0, current), max(0, total), finished)
            fractions: list[float] = []
            for received, expected, completed in byte_state.values():
                if completed:
                    fractions.append(1.0)
                elif expected > 0:
                    fractions.append(min(1.0, received / expected))
                elif received > 0:
                    # Unknown Content-Length: provide conservative progress until completion.
                    fractions.append(min(0.9, received / (received + 256 * 1024)))
                else:
                    fractions.append(0.0)
            percent = int(round((sum(fractions) / max(1, len(fractions))) * 100))
        if progress:
            progress(percent, 100)

    def complete(source_id: str) -> None:
        with state_lock:
            received, expected, _ = byte_state[source_id]
        report(source_id, received or expected or 1, expected or received or 1, finished=True)

    rows_by_source: dict[str, list[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(enabled)))) as executor:
        futures = {
            executor.submit(_fetch_subscription, source, lambda current, total, sid=source.id: report(sid, current, total)): source
            for source in enabled
        }
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                rows = future.result()
            except Exception as exc:
                rows = []
                errors.append(f"{source.name}: {exc}")
            rows_by_source[source.id] = rows
            complete(source.id)

    # Attribute duplicates deterministically to the first source in user-defined order.
    for source in enabled:
        for raw in rows_by_source.get(source.id, []):
            key = normalize_key(raw)
            if not key or key in seen:
                continue
            seen.add(key)
            found.append(
                DiscoveredConfig(
                    raw=raw,
                    source_id=source.id,
                    source_name=source.name,
                    source_order=source.order,
                )
            )
            if len(found) >= MAX_DISCOVERY_CONFIGS:
                break
        if len(found) >= MAX_DISCOVERY_CONFIGS:
            break

    if progress:
        progress(100, 100)
    if not found:
        detail = errors[-1] if errors else tr(language, "source_fetch_failed")
        raise RuntimeError(f"{tr(language, 'source_fetch_failed')}\n{detail}")
    return found[:MAX_DISCOVERY_CONFIGS]


def discover_configs(
    custom_urls: list[str] | tuple[str, ...] | None = None,
    stage: StageCallback | None = None,
    progress: ProgressCallback | None = None,
    language: str = "fa",
) -> list[str]:
    """Backward-compatible raw-config API used by older tests/integrations."""
    sources = [
        SourceDefinition(
            id="default" if index == 0 else source_id_for_url(url),
            name=("منبع اصلی" if index == 0 else f"منبع {index + 1}"),
            url=url,
            order=index,
            enabled=True,
            is_default=index == 0,
        )
        for index, url in enumerate(normalize_subscription_urls(custom_urls))
    ]
    return [entry.raw for entry in discover_config_entries(sources, stage=stage, progress=progress, language=language)]
