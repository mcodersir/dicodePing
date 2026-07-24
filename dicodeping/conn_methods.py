"""Connection method configuration for dicodePing.

v1.7.0-rc.1 introduces three connection methods:

  1. ``xray`` (default) — the standard dicodePing path using Xray-core.
  2. ``psiphon`` — alternative core using the Psiphon circumvention
     protocol.  Downloaded on first use via the core manager.
  3. ``aether`` — alternative core with the Ironclad real-tunnel scan
     mode.  Downloaded on first use via the core manager.

When a non-default method is active, the Servers page is effectively
disabled in the UI because the alternative cores do not use the
per-server config-blob model.  The user toggles the method in Settings;
the splash screen skips the server-list pipeline when a non-default
method is active.

This module also provides the ``apply_cdn_formatting`` helper that
rewrites a config URI to use a CDN fronting domain, as requested by
the user.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from .diagnostics import get_logger

LOGGER = get_logger("conn_methods")

# Known connection methods.
METHOD_XRAY = "xray"
METHOD_PSION = "psiphon"
METHOD_AETHER = "aether"

ALL_METHODS = (METHOD_XRAY, METHOD_PSION, METHOD_AETHER)


@dataclass(frozen=True, slots=True)
class ConnectionMethod:
    id: str
    name: str
    description: str
    requires_core_download: bool


METHOD_CATALOG: dict[str, ConnectionMethod] = {
    METHOD_XRAY: ConnectionMethod(
        id=METHOD_XRAY,
        name="Xray-core (پیش‌فرض)",
        description="روش پیش‌فرض dicodePing. از سرورهای موجود در لیست استفاده می‌کند.",
        requires_core_download=False,
    ),
    METHOD_PSION: ConnectionMethod(
        id=METHOD_PSION,
        name="Psiphon",
        description="هسته جایگزین با پروتکل دور زدن Psiphon. هسته در اولین استفاده دانلود می‌شود. در این حالت صفحه سرورها غیرفعال است.",
        requires_core_download=True,
    ),
    METHOD_AETHER: ConnectionMethod(
        id=METHOD_AETHER,
        name="Aether (Ironclad)",
        description="هسته جایگزین با حالت اسکن Ironclad که قبل از اعتماد به سرور یک تانل واقعی برقرار می‌کند. هسته در اولین استفاده دانلود می‌شود. در این حالت صفحه سرورها غیرفعال است.",
        requires_core_download=True,
    ),
}


def list_methods() -> list[ConnectionMethod]:
    return list(METHOD_CATALOG.values())


def get_method(method_id: str) -> ConnectionMethod | None:
    return METHOD_CATALOG.get(method_id)


def is_default_method(method_id: str) -> bool:
    return method_id == METHOD_XRAY


# --- CDN formatting -----------------------------------------------------

# A small set of well-known CDN fronting domains.  The user can edit
# this list in settings.  When CDN formatting is enabled, the host of
# each config URI is rewritten to the chosen CDN domain and the
# original host is passed via the SNI / Host header (handled by xray's
# ``domainStrategy`` and ``host`` field in streamSettings).
DEFAULT_CDN_DOMAINS = (
    "speed.cloudflare.com",
    "www.cloudflare.com",
    "www.bing.com",
    "www.microsoft.com",
    "discord.com",
    "www.amazon.com",
)


def apply_cdn_formatting(raw_config: str, cdn_domain: str) -> str:
    """Rewrite a config URI to use a CDN fronting domain.

    For vmess:// URIs the JSON body's ``add`` field is replaced with
    the CDN domain and the original host is preserved in the ``host``
    field of ``streamSettings`` (if present) or as a remark.  For
    vless://, trojan://, ss:// URIs the URL host is replaced and the
    original host is stored in a ``?host=`` query parameter that the
    xray config builder can pick up.

    Returns the rewritten URI.  If the URI cannot be parsed, it is
    returned unchanged.
    """
    if not raw_config or not cdn_domain:
        return raw_config
    try:
        if raw_config.lower().startswith("vmess://"):
            return _rewrite_vmess(raw_config, cdn_domain)
        if raw_config.lower().startswith(("vless://", "trojan://")):
            return _rewrite_url_config(raw_config, cdn_domain)
        # ss:// is more complex (base64 body); leave unchanged for now.
        return raw_config
    except Exception as exc:
        LOGGER.debug("CDN formatting failed for config: %s", exc)
        return raw_config


def _rewrite_vmess(raw: str, cdn_domain: str) -> str:
    import base64
    import json

    body = raw[len("vmess://"):].split("#", 1)[0]
    # vmess body is base64-encoded JSON.
    padded = body + "=" * ((4 - len(body) % 4) % 4)
    obj = json.loads(base64.b64decode(padded).decode("utf-8"))
    original_host = str(obj.get("add") or "")
    if not original_host:
        return raw
    obj["add"] = cdn_domain
    # Preserve the original host in the ``host`` field of the stream
    # settings so xray can use it as the SNI / Host header.
    if "host" not in obj or not obj["host"]:
        obj["host"] = original_host
    new_body = base64.b64encode(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    remark = raw.split("#", 1)[1] if "#" in raw else ""
    return "vmess://" + new_body + ("#" + remark if remark else "")


def _rewrite_url_config(raw: str, cdn_domain: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    if not parsed.hostname:
        return raw
    original_host = parsed.hostname
    # Replace the host in the netloc.
    netloc = cdn_domain
    if parsed.port:
        netloc = f"{cdn_domain}:{parsed.port}"
    # Append the original host as a query parameter.
    query = parsed.query
    if "host=" not in query:
        query = (query + "&" if query else "") + f"host={urllib.parse.quote(original_host)}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, parsed.path, query, parsed.fragment)
    )
