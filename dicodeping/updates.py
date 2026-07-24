from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Iterable

from .models import SourceDefinition
from .constants import DEFAULT_SUBSCRIPTION_MIRRORS

RELEASES_URL = "https://api.github.com/repos/mcodersir/dicodePing/releases"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    name: str
    page_url: str
    asset_url: str


def _version(value: str) -> tuple[int, int, int, int, int]:
    matched = _VERSION.match(str(value).strip())
    if not matched:
        return (0, 0, 0, 0, 0)
    major, minor, patch, rc = matched.groups()
    # A stable build is newer than its matching release candidate.
    return (int(major), int(minor), int(patch), 1 if rc is None else 0, int(rc or 0))


def find_application_update(current_version: str, platform: str, timeout: float = 3.5) -> ReleaseInfo | None:
    request = urllib.request.Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "dicodePing"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if not isinstance(rows, list):
        return None
    current = _version(current_version)
    best: tuple[tuple[int, int, int, int, int], ReleaseInfo] | None = None
    token = {"windows": "-windows.exe", "linux": "-linux-", "android": "-android.apk"}.get(platform, "")
    for row in rows:
        # This one-time release exists only so pre-RC.4 clients can escape the
        # old same-series comparison bug. New clients must never offer it.
        if str(row.get("name") or "").startswith("Compatibility bridge"):
            continue
        tag = str(row.get("tag_name") or "")
        candidate = _version(tag)
        same_series_candidate = (
            "-rc." not in str(current_version).lower()
            and candidate[:3] == current[:3]
            and candidate[3] == 0
        )
        if candidate <= current and not same_series_candidate:
            continue
        assets = row.get("assets") if isinstance(row.get("assets"), list) else []
        asset = next((item for item in assets if token and token in str(item.get("name") or "")), None)
        page_url = str(row.get("html_url") or "")
        asset_url = str((asset or {}).get("browser_download_url") or page_url)
        if not asset_url:
            continue
        info = ReleaseInfo(tag, str(row.get("name") or tag), page_url, asset_url)
        if best is None or candidate > best[0]:
            best = (candidate, info)
    return best[1] if best else None


def source_revision(source: SourceDefinition, timeout: float = 2.5) -> str:
    candidates = DEFAULT_SUBSCRIPTION_MIRRORS if source.is_default or source.id == "default" else (source.url,)
    for url in dict.fromkeys(candidates):
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "dicodePing"})
        for opener in (urllib.request.build_opener(), urllib.request.build_opener(urllib.request.ProxyHandler({}))):
            try:
                with opener.open(request, timeout=timeout) as response:
                    headers = response.headers
                    revision = "|".join((headers.get("ETag", ""), headers.get("Last-Modified", ""), headers.get("Content-Length", "")))
                    if revision.strip("|"):
                        return revision
            except Exception:
                continue
    return ""


def check_source_updates(
    sources: Iterable[SourceDefinition],
    known: dict[str, str] | None,
) -> tuple[list[SourceDefinition], dict[str, str]]:
    previous = known if isinstance(known, dict) else {}
    changed: list[SourceDefinition] = []
    observed: dict[str, str] = {}
    for source in sources:
        if not source.enabled:
            continue
        revision = source_revision(source)
        if not revision:
            continue
        observed[source.id] = revision
        if previous.get(source.id) and previous.get(source.id) != revision:
            changed.append(source)
    return changed, observed
