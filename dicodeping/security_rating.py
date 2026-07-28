"""Conservative display-only security assessment for proxy configurations.

The score is intentionally not a cryptographic audit. It only evaluates
signals visible in the subscription URI: transport encryption, certificate
verification hints, protocol age, and risky compatibility flags.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit


@dataclass(frozen=True, slots=True)
class SecurityAssessment:
    score: int
    level: str
    summary: str
    reasons: tuple[str, ...]


def _first(query: dict[str, list[str]], *names: str) -> str:
    for name in names:
        values = query.get(name)
        if values:
            return str(values[0]).strip().lower()
    return ""


def assess_config_security(raw: str, host: str = "") -> SecurityAssessment:
    text = unquote(raw or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        parsed = urlsplit("")
    scheme = parsed.scheme.lower()
    query = {str(k).lower(): [str(v) for v in values] for k, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    security = _first(query, "security", "tls")
    transport = _first(query, "type", "net", "network")
    sni = _first(query, "sni", "servername", "server_name", "host")
    allow_insecure = _first(query, "allowinsecure", "insecure", "skip-cert-verify") in {"1", "true", "yes", "on"}

    score = 48
    reasons: list[str] = []

    if security == "reality":
        score += 34
        reasons.append("Reality با احراز هویت مقصد")
    elif security in {"tls", "xtls"}:
        score += 27
        reasons.append("رمزنگاری TLS فعال")
    elif scheme in {"trojan", "hysteria2", "hy2", "tuic"}:
        score += 23
        reasons.append("پروتکل دارای لایه رمزنگاری داخلی")
    elif scheme in {"ss", "shadowsocks"}:
        score += 12
        reasons.append("رمزنگاری Shadowsocks")
    else:
        score -= 18
        reasons.append("رمزنگاری انتقال صریح تشخیص داده نشد")

    if sni or (host and not _looks_like_ip(host)):
        score += 7
        reasons.append("نام میزبان/SNI مشخص است")
    if transport in {"ws", "grpc", "httpupgrade", "splithttp", "xhttp", "h2", "quic"}:
        score += 4
        reasons.append("انتقال مدرن یا استتارشده")
    if allow_insecure:
        score -= 24
        reasons.append("اعتبارسنجی گواهی غیرفعال است")
    if scheme == "vmess":
        score -= 5
        reasons.append("VMess برای سازگاری نگه‌داری می‌شود")
    if scheme in {"http", "socks"}:
        score -= 28
        reasons.append("پروکسی خام بدون تضمین رمزنگاری")

    score = max(10, min(96, score))
    if score >= 78:
        level = "high"
        summary = "امنیت خوب"
    elif score >= 55:
        level = "standard"
        summary = "امنیت معمولی"
    else:
        level = "basic"
        summary = "امنیت پایه"
    return SecurityAssessment(score, level, summary, tuple(reasons[:4]))


def _looks_like_ip(value: str) -> bool:
    value = value.strip().strip("[]")
    if not value:
        return False
    if ":" in value:
        return all(part == "" or all(ch in "0123456789abcdefABCDEF" for ch in part) for part in value.split(":"))
    parts = value.split(".")
    return len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)
