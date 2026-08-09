"""v2rayN-based protocol parsing for dicodePing Version 3.

Parses v2rayN-format configurations (vless, vmess, trojan, ss)
and extracts server endpoint details.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
from typing import Any

from .models import Endpoint

SUPPORTED_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://")

CONFIG_REGEXES = [
    re.compile(r"(?:vless|vmess|trojan|ss)://[^\s<>'\"]+", re.I),
]


def _b64_decode_text(value: str) -> str:
    """Decode a base64-encoded string."""
    text = value.strip().replace("-", "+").replace("_", "/")
    text += "=" * ((4 - len(text) % 4) % 4)
    return base64.b64decode(text).decode("utf-8", errors="ignore")


def _b64_encode_text(value: str, urlsafe: bool = False) -> str:
    """Encode a string to base64."""
    raw = value.encode("utf-8")
    data = base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)
    return data.decode("ascii").rstrip("=")


def decode_subscription(text: str) -> list[str]:
    """Decode a subscription text and extract individual server configs."""
    value = text.strip().lstrip("\ufeff")
    if not value:
        return []
    if "://" not in value[:1000]:
        try:
            decoded = _b64_decode_text("".join(value.split()))
            if "://" in decoded:
                value = decoded
        except Exception:
            pass
    return extract_configs(value)


def extract_configs(text: str) -> list[str]:
    """Extract server configurations from a subscription text."""
    text = html.unescape(text)
    text = re.sub(r"[\u200c\u200f\u202a-\u202e]", "", text)
    out: list[str] = []
    seen: set[str] = set()
    for regex in CONFIG_REGEXES:
        for match in regex.findall(text):
            raw = match.strip().rstrip(")]}\"'<>")
            key = normalize_key(raw)
            if key and key not in seen:
                seen.add(key)
                out.append(raw)
    return out


def normalize_key(raw: str) -> str:
    """Normalize a key for duplicate detection."""
    raw = raw.strip()
    if raw.lower().startswith("vmess://"):
        try:
            obj = json.loads(_b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
            obj.pop("ps", None)
            return "vmess://" + json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return raw
    return raw.split("#", 1)[0]


def parse_int(value: Any, default: int = 0) -> int:
    """Parse an integer with a default value."""
    try:
        return int(str(value))
    except Exception:
        return default


def valid_port(port: int) -> bool:
    """Validate a port number."""
    return 0 < port <= 65535


def parse_host_port(value: str) -> tuple[str, int] | None:
    """Parse a host:port string into a host and port."""
    text = value.strip()
    if text.startswith("["):
        end = text.find("]")
        if end < 0 or not text[end + 1 :].startswith(":"):
            return None
        host, port = text[1:end], parse_int(text[end + 2 :])
    else:
        idx = text.rfind(":")
        if idx < 0:
            return None
        host, port = text[:idx], parse_int(text[idx + 1 :])
    return (host, port) if host and valid_port(port) else None


def parse_ss_share(raw: str) -> tuple[str, str, str, int] | None:
    """Parse an SS share config."""
    body = raw[len("ss://") :].split("#", 1)[0]
    parsed = urllib.parse.urlsplit("ss://" + body)
    if parsed.hostname and parsed.username and parsed.password:
        return (
            urllib.parse.unquote(parsed.username),
            urllib.parse.unquote(parsed.password),
            parsed.hostname,
            parsed.port or 8388,
        )
    core = urllib.parse.unquote(body.split("?", 1)[0])
    if "@" not in core:
        core = _b64_decode_text(core)
    if "@" not in core:
        return None
    userinfo, host_port = core.rsplit("@", 1)
    if ":" not in userinfo:
        userinfo = _b64_decode_text(userinfo)
    if ":" not in userinfo:
        return None
    method, password = userinfo.split(":", 1)
    hp = parse_host_port(host_port)
    if not hp:
        return None
    return method, password, hp[0], hp[1]


def parse_endpoint(raw: str) -> Endpoint | None:
    """Parse a raw server configuration string into an Endpoint."""
    lower = raw.lower().strip()
    try:
        if lower.startswith("vless://") or lower.startswith("trojan://"):
            parsed = urllib.parse.urlsplit(raw)
            if not parsed.hostname:
                return None
            return Endpoint(raw, parsed.scheme.lower(), parsed.hostname, parsed.port or 443)
        if lower.startswith("vmess://"):
            obj = json.loads(_b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
            host = obj.get("add") or obj.get("address") or obj.get("server")
            port = parse_int(obj.get("port"), 443)
            if not host or not valid_port(port):
                return None
            return Endpoint(raw, "vmess", str(host), port)
        if lower.startswith("ss://"):
            parsed_ss = parse_ss_share(raw)
            if not parsed_ss:
                return None
            return Endpoint(raw, "ss", parsed_ss[2], parsed_ss[3])
    except Exception:
        return None
    return None


def first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    """Get the first value from a query dict."""
    values = query.get(key)
    return values[0] if values else default


def bool_query(query: dict[str, list[str]], *keys: str) -> bool:
    """Check if any of the provided keys have a truthy value."""
    for key in keys:
        value = first(query, key)
        if value:
            return value.lower() in {"1", "true", "yes"}
    return False


def csv_list(value: str) -> list[str]:
    """Parse a comma-separated list."""
    return [item.strip() for item in value.split(",") if item.strip()]


def build_stream_settings(parsed: urllib.parse.SplitResult, query: dict[str, list[str]]) -> dict[str, Any]:
    """Build stream settings from a parsed URL and query parameters."""
    network = (first(query, "type", first(query, "net", "tcp")) or "tcp").strip().lower()
    if network == "raw":
        network = "tcp"
    security = (first(query, "security", "none") or "none").strip().lower()
    host = first(query, "host", "").strip()
    stream: dict[str, Any] = {"network": network}

    if security != "none":
        stream["security"] = security
        sni = first(query, "sni", first(query, "serverName", first(query, "peer", ""))).strip()
        if not sni and host:
            sni = host.split(",", 1)[0].strip()
        fp = first(query, "fp", first(query, "fingerprint", ""))
        alpn = csv_list(first(query, "alpn", ""))
        if security == "tls":
            tls: dict[str, Any] = {"allowInsecure": bool_query(query, "allowInsecure", "insecure")}
            if sni:
                tls["serverName"] = sni
            if fp:
                tls["fingerprint"] = fp
            if alpn:
                tls["alpn"] = alpn
            stream["tlsSettings"] = tls
        elif security == "reality":
            reality: dict[str, Any] = {}
            if sni:
                reality["serverName"] = sni
            if fp:
                reality["fingerprint"] = fp
            for key, target in (("pbk", "publicKey"), ("sid", "shortId"), ("spx", "spiderX")):
                value = first(query, key, first(query, target, ""))
                if value:
                    reality[target] = urllib.parse.unquote(value)
            stream["realitySettings"] = reality

    path = urllib.parse.unquote(first(query, "path", first(query, "serviceName", "")))
    header_type = first(query, "headerType", first(query, "header", "none")) or "none"

    if network in {"ws", "websocket"}:
        settings: dict[str, Any] = {}
        if path:
            settings["path"] = path
        if host:
            settings["host"] = host
        heartbeat = parse_int(first(query, "heartbeatPeriod", first(query, "heartbeat", "0")))
        if heartbeat > 0:
            settings["heartbeatPeriod"] = heartbeat
        stream["network"] = "ws"
        stream["wsSettings"] = settings
    elif network == "grpc":
        settings = {}
        if path:
            settings["serviceName"] = path
        if host:
            settings["authority"] = host
        if first(query, "mode").lower() == "multi":
            settings["multiMode"] = True
        user_agent = first(query, "user_agent", first(query, "userAgent", ""))
        if user_agent:
            settings["user_agent"] = urllib.parse.unquote(user_agent)
        numeric_keys = (
            ("idle_timeout", "idle_timeout"),
            ("health_check_timeout", "health_check_timeout"),
            ("initial_windows_size", "initial_windows_size"),
        )
        for source_key, target_key in numeric_keys:
            value = parse_int(first(query, source_key, "0"))
            if value > 0:
                settings[target_key] = value
        if bool_query(query, "permit_without_stream"):
            settings["permit_without_stream"] = True
        stream["grpcSettings"] = settings
    elif network.lower() == "httpupgrade":
        settings = {}
        if path:
            settings["path"] = path
        if host:
            settings["host"] = host
        stream["network"] = "httpupgrade"
        stream["httpupgradeSettings"] = settings
    elif network in {"xhttp", "splithttp"}:
        settings = {}
        if path:
            settings["path"] = path
        if host:
            settings["host"] = host
        mode = first(query, "mode")
        if mode:
            settings["mode"] = mode
        extra = first(query, "extra")
        if extra:
            try:
                extra_obj = json.loads(urllib.parse.unquote(extra))
                if isinstance(extra_obj, dict):
                    settings.update(extra_obj)
            except Exception:
                pass
        stream["network"] = "xhttp"
        stream["xhttpSettings"] = settings
    elif network in {"h2", "http"}:
        settings = {}
        if path:
            settings["path"] = path
        if host:
            settings["host"] = [host]
        stream["network"] = "http"
        stream["httpSettings"] = settings
    elif network == "tcp" and header_type != "none":
        header: dict[str, Any] = {"type": header_type}
        if header_type == "http":
            request: dict[str, Any] = {}
            if path:
                request["path"] = [path]
            if host:
                request["headers"] = {"Host": [host]}
            header["request"] = request
        stream["tcpSettings"] = {"header": header}
    return stream


def build_vmess_stream(obj: dict[str, Any]) -> dict[str, Any]:
    """Build vmess stream settings from a parsed VMESS object."""
    query = {
        "type": [str(obj.get("net") or "tcp")],
        "security": [str(obj.get("tls") or obj.get("security") or "none")],
        "host": [str(obj.get("host") or "")],
        "path": [str(obj.get("path") or "")],
        "sni": [str(obj.get("sni") or obj.get("peer") or "")],
        "alpn": [str(obj.get("alpn") or "")],
        "headerType": [str(obj.get("type") or obj.get("headerType") or "none")],
        "allowInsecure": [str(obj.get("allowInsecure") or "0")],
    }
    return build_stream_settings(urllib.parse.SplitResult("vmess", "", "", "", ""), query)


def build_xray_outbound(raw: str) -> dict[str, Any] | None:
    """Build an Xray outbound configuration from a raw server string."""
    lower = raw.lower().strip()
    try:
        if lower.startswith("vless://"):
            parsed = urllib.parse.urlsplit(raw)
            query = urllib.parse.parse_qs(parsed.query)
            if not parsed.hostname or not parsed.username:
                return None
            user: dict[str, Any] = {
                "id": urllib.parse.unquote(parsed.username),
                "encryption": first(query, "encryption", "none") or "none",
            }
            flow = first(query, "flow")
            if flow:
                user["flow"] = flow
            packet_encoding = first(query, "packetEncoding", first(query, "packetencoding", ""))
            if packet_encoding:
                user["packetEncoding"] = packet_encoding
            return {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": parsed.hostname, "port": parsed.port or 443, "users": [user]}]},
                "streamSettings": build_stream_settings(parsed, query),
            }
        if lower.startswith("vmess://"):
            obj = json.loads(_b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
            host = obj.get("add") or obj.get("address") or obj.get("server")
            user_id = str(obj.get("id") or "")
            if not host or not user_id:
                return None
            return {
                "tag": "proxy",
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": str(host),
                        "port": parse_int(obj.get("port"), 443),
                        "users": [{
                            "id": user_id,
                            "alterId": parse_int(obj.get("aid"), 0),
                            "security": str(obj.get("scy") or "auto"),
                        }],
                    }]
                },
                "streamSettings": build_vmess_stream(obj),
            }
        if lower.startswith("trojan://"):
            parsed = urllib.parse.urlsplit(raw)
            query = urllib.parse.parse_qs(parsed.query)
            if not parsed.hostname or not parsed.username:
                return None
            return {
                "tag": "proxy",
                "protocol": "trojan",
                "settings": {"servers": [{
                    "address": parsed.hostname,
                    "port": parsed.port or 443,
                    "password": urllib.parse.unquote(parsed.username),
                }]},
                "streamSettings": build_stream_settings(parsed, query),
            }
        if lower.startswith("ss://"):
            parsed_ss = parse_ss_share(raw)
            if not parsed_ss:
                return None
            method, password, host, port = parsed_ss
            return {
                "tag": "proxy",
                "protocol": "shadowsocks",
                "settings": {"servers": [{"address": host, "port": port, "method": method, "password": password}]},
            }
    except Exception:
        return None
    return None


def set_display_name(raw: str, name: str) -> str:
    """Set a display name for a VMESS config."""
    if raw.lower().startswith("vmess://"):
        try:
            obj = json.loads(_b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
            obj["ps"] = name
            return "vmess://" + _b64_encode_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), True) + "#" + urllib.parse.quote(name)
        except Exception:
            return raw
    return raw.split("#", 1)[0] + "#" + urllib.parse.quote(name)


def record_id(raw: str) -> str:
    """Generate a record ID from a raw config string."""
    return hashlib.sha256(normalize_key(raw).encode("utf-8", errors="ignore")).hexdigest()[:16]


def config_to_blob(raw: str) -> str:
    """Convert a raw config to a base64 blob."""
    return _b64_encode_text(raw, True)


def blob_to_config(blob: str) -> str:
    """Convert a base64 blob back to a raw config."""
    return _b64_decode_text(blob)
