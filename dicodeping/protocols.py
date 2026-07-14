from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import urllib.parse
from typing import Any

from .models import Endpoint

SUPPORTED_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://")
CONFIG_REGEXES = [
    re.compile(r"(?:vless|vmess|trojan|ss)://[^\s<>'\"]+", re.I),
]


def b64_decode_text(value: str) -> str:
    text = value.strip().replace("-", "+").replace("_", "/")
    text += "=" * ((4 - len(text) % 4) % 4)
    return base64.b64decode(text).decode("utf-8", errors="ignore")


def b64_encode_text(value: str, urlsafe: bool = False) -> str:
    raw = value.encode("utf-8")
    data = base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)
    return data.decode("ascii").rstrip("=")


def decode_subscription(text: str) -> list[str]:
    value = text.strip().lstrip("\ufeff")
    if not value:
        return []
    if "://" not in value[:1000]:
        try:
            decoded = b64_decode_text("".join(value.split()))
            if "://" in decoded:
                value = decoded
        except Exception:
            pass
    return extract_configs(value)


def extract_configs(text: str) -> list[str]:
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
    raw = raw.strip()
    if raw.lower().startswith("vmess://"):
        try:
            obj = json.loads(b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
            obj.pop("ps", None)
            return "vmess://" + json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return raw
    return raw.split("#", 1)[0]


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def valid_port(port: int) -> bool:
    return 0 < port <= 65535


def parse_host_port(value: str) -> tuple[str, int] | None:
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
        core = b64_decode_text(core)
    if "@" not in core:
        return None
    userinfo, host_port = core.rsplit("@", 1)
    if ":" not in userinfo:
        userinfo = b64_decode_text(userinfo)
    if ":" not in userinfo:
        return None
    method, password = userinfo.split(":", 1)
    hp = parse_host_port(host_port)
    if not hp:
        return None
    return method, password, hp[0], hp[1]


def parse_endpoint(raw: str) -> Endpoint | None:
    lower = raw.lower().strip()
    try:
        if lower.startswith("vless://") or lower.startswith("trojan://"):
            parsed = urllib.parse.urlsplit(raw)
            if not parsed.hostname:
                return None
            return Endpoint(raw, parsed.scheme.lower(), parsed.hostname, parsed.port or 443)
        if lower.startswith("vmess://"):
            obj = json.loads(b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
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
    values = query.get(key)
    return values[0] if values else default


def bool_query(query: dict[str, list[str]], *keys: str) -> bool:
    for key in keys:
        value = first(query, key)
        if value:
            return value.lower() in {"1", "true", "yes"}
    return False


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_stream_settings(parsed: urllib.parse.SplitResult, query: dict[str, list[str]]) -> dict[str, Any]:
    network = first(query, "type", first(query, "net", "tcp")) or "tcp"
    security = first(query, "security", "none") or "none"
    stream: dict[str, Any] = {"network": network}

    if security != "none":
        stream["security"] = security
        sni = first(query, "sni", first(query, "serverName", first(query, "peer", "")))
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

    host = first(query, "host", "")
    path = urllib.parse.unquote(first(query, "path", first(query, "serviceName", "")))
    header_type = first(query, "headerType", first(query, "header", "none")) or "none"

    if network == "ws":
        settings: dict[str, Any] = {}
        if path:
            settings["path"] = path
        if host:
            settings["host"] = host
        stream["wsSettings"] = settings
    elif network == "grpc":
        settings = {}
        if path:
            settings["serviceName"] = path
        if first(query, "mode") == "multi":
            settings["multiMode"] = True
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
            return {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": parsed.hostname, "port": parsed.port or 443, "users": [user]}]},
                "streamSettings": build_stream_settings(parsed, query),
            }
        if lower.startswith("vmess://"):
            obj = json.loads(b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
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
    if raw.lower().startswith("vmess://"):
        try:
            obj = json.loads(b64_decode_text(raw[len("vmess://") :].split("#", 1)[0]))
            obj["ps"] = name
            return "vmess://" + b64_encode_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), True) + "#" + urllib.parse.quote(name)
        except Exception:
            return raw
    return raw.split("#", 1)[0] + "#" + urllib.parse.quote(name)


def record_id(raw: str) -> str:
    return hashlib.sha256(normalize_key(raw).encode("utf-8", errors="ignore")).hexdigest()[:16]


def config_to_blob(raw: str) -> str:
    return b64_encode_text(raw, True)


def blob_to_config(blob: str) -> str:
    return b64_decode_text(blob)
