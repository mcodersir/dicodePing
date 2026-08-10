from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import urllib.parse
from typing import Any

from .models import Endpoint

SUPPORTED_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")
CONFIG_REGEXES = [
    re.compile(r"(?:vless|vmess|trojan|ss|hysteria2|hy2)://[^\s<>'\"]+", re.I),
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
        if lower.startswith(("vless://", "trojan://", "hysteria2://", "hy2://")):
            parsed = urllib.parse.urlsplit(raw)
            if not parsed.hostname:
                return None
            protocol = "hysteria2" if parsed.scheme.lower() == "hy2" else parsed.scheme.lower()
            return Endpoint(raw, protocol, parsed.hostname, parsed.port or 443)
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

