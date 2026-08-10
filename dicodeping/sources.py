from __future__ import annotations

import hashlib
from typing import Any

from .constants import DEFAULT_SUBSCRIPTION_URL, MAX_CUSTOM_SUBSCRIPTIONS
from .models import SourceDefinition


def source_id_for_url(url: str) -> str:
    value = url.strip()
    if value == DEFAULT_SUBSCRIPTION_URL:
        return "default"
    return "src-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def default_source_name(language: str = "fa") -> str:
    return "منبع اصلی" if language != "en" else "Primary source"


def _primary(language: str) -> SourceDefinition:
    return SourceDefinition(
        id="default",
        name=default_source_name(language),
        url=DEFAULT_SUBSCRIPTION_URL,
        order=0,
        enabled=True,
        is_default=True,
    )


def normalize_sources(settings: dict[str, Any], language: str = "fa") -> list[SourceDefinition]:
    """Return the Version 3 source set with the product source always authoritative."""
    rows: list[SourceDefinition] = [_primary(language)]
    stored = settings.get("sources")
    if isinstance(stored, list):
        for raw in stored:
            if not isinstance(raw, dict):
                continue
            item = SourceDefinition.from_dict(raw)
            item.url = item.url.strip()
            if item.is_default or item.id == "default" or item.url == DEFAULT_SUBSCRIPTION_URL:
                continue
            if not item.url.lower().startswith(("http://", "https://")):
                continue
            item.id = item.id or source_id_for_url(item.url)
            item.name = item.name.strip() or ("منبع" if language != "en" else "Source")
            rows.append(item)

    deduped: list[SourceDefinition] = []
    seen: set[str] = set()
    for item in rows:
        key = item.url.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= MAX_CUSTOM_SUBSCRIPTIONS + 1:
            break
    for order, item in enumerate(deduped):
        item.order = order
    return deduped


def serialize_sources(sources: list[SourceDefinition]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for order, source in enumerate(sources):
        source.order = order
        normalized.append(source.to_dict())
    return normalized
