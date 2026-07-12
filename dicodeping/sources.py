from __future__ import annotations

import hashlib
from typing import Any

from .constants import DEFAULT_SUBSCRIPTION_URL, MAX_CUSTOM_SUBSCRIPTIONS
from .models import SourceDefinition


def source_id_for_url(url: str) -> str:
    if url.strip() == DEFAULT_SUBSCRIPTION_URL:
        return "default"
    return "src-" + hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:12]


def default_source_name(language: str = "fa") -> str:
    return "منبع اصلی" if language != "en" else "Primary source"


def normalize_sources(settings: dict[str, Any], language: str = "fa") -> list[SourceDefinition]:
    stored = settings.get("sources")
    rows: list[SourceDefinition] = []
    if isinstance(stored, list):
        for raw in stored:
            if not isinstance(raw, dict):
                continue
            item = SourceDefinition.from_dict(raw)
            item.url = item.url.strip()
            if not item.url.lower().startswith(("http://", "https://")):
                continue
            item.id = item.id or source_id_for_url(item.url)
            item.name = item.name.strip() or default_source_name(language)
            rows.append(item)

    # Migration from the older custom_subscriptions setting.
    if not rows:
        rows.append(
            SourceDefinition(
                id="default",
                name=str(settings.get("default_source_name") or default_source_name(language)),
                url=DEFAULT_SUBSCRIPTION_URL,
                order=0,
                enabled=True,
                is_default=True,
            )
        )
        custom = settings.get("custom_subscriptions", [])
        for index, url in enumerate(custom if isinstance(custom, list) else [], start=1):
            value = str(url or "").strip()
            if value.lower().startswith(("http://", "https://")):
                rows.append(
                    SourceDefinition(
                        id=source_id_for_url(value),
                        name=(f"منبع {index + 1}" if language != "en" else f"Source {index + 1}"),
                        url=value,
                        order=index,
                        enabled=True,
                    )
                )

    default = next((item for item in rows if item.is_default or item.id == "default" or item.url == DEFAULT_SUBSCRIPTION_URL), None)
    if default is None:
        default = SourceDefinition(
            id="default",
            name=default_source_name(language),
            url=DEFAULT_SUBSCRIPTION_URL,
            order=-1,
            enabled=True,
            is_default=True,
        )
        rows.insert(0, default)
    default.id = "default"
    default.url = DEFAULT_SUBSCRIPTION_URL
    default.is_default = True
    default.enabled = True
    default.name = default.name.strip() or default_source_name(language)

    deduped: list[SourceDefinition] = []
    seen_urls: set[str] = set()
    for item in sorted(rows, key=lambda row: (row.order, row.name.casefold())):
        key = item.url.casefold()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        item.id = "default" if item.is_default else (item.id or source_id_for_url(item.url))
        deduped.append(item)
        if len(deduped) >= MAX_CUSTOM_SUBSCRIPTIONS + 1:
            break
    for order, item in enumerate(deduped):
        item.order = order
    return deduped


def serialize_sources(sources: list[SourceDefinition]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for order, source in enumerate(sources):
        source.order = order
        result.append(source.to_dict())
    return result
