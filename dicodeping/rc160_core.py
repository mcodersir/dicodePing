from __future__ import annotations

import concurrent.futures
import html
import re
import socket
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from statistics import median, pstdev
from typing import Callable, Iterable

from .models import ServerRecord, SourceDefinition, utc_now
from .net import resolve_ipv4
from .protocols import config_to_blob, normalize_key, parse_endpoint, record_id, set_display_name
from .xray import XrayManager, probe_outbound_delay

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]

# Deliberately curated and internal. RC1 exposes one Scan action instead of the
# channel/update controls from DicodeConfigChecker.
SCANNER_CHANNELS = (
    "v2rayngvpn", "ConfigX2ray", "V2rayConfigList", "vlesskeys",
    "Daily_Configs", "v2rayshare", "vless_vmess", "V2rayNGconfig",
    "VmessProtocol", "v2nodes", "DirectVPN", "Everyday_VPN",
    "v2ray_configs_pool", "V2rayng_Fast", "freewireguard", "warpscanner",
)

_CONFIG_RX = re.compile(
    r"\b(?:vmess|vless|trojan|ss|ssr|snell|hysteria2|hy2|tuic)://[^\s<>\"'`\\]+",
    re.IGNORECASE,
)
_TRAFFIC_RX = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*(TB|GB|MB)\b")


@dataclass(slots=True)
class ScanSummary:
    source: SourceDefinition
    records: list[ServerRecord]
    fetched: int
    tested: int
    elapsed_seconds: int


@dataclass(slots=True)
class SubscriptionUsage:
    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0
    status: str = "unknown"
    source: str = ""

    @property
    def used(self) -> int:
        return max(0, self.upload) + max(0, self.download)


def _clean_config(raw: str) -> str:
    value = html.unescape(raw).replace("\\u0026", "&").replace("&amp;", "&").strip()
    value = re.sub(r"[\u200c\u200f\u202a-\u202e]", "", value)
    return value.rstrip(")]}'\"<>،,.;")


def extract_configs(page: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _CONFIG_RX.findall(page or ""):
        raw = _clean_config(match)
        key = normalize_key(raw)
        if not raw or not key or key in seen or not parse_endpoint(raw):
            continue
        seen.add(key)
        found.append(raw)
    found.reverse()
    return found


def _fetch_preview(channel: str, timeout: float = 9.0) -> list[str]:
    errors: list[str] = []
    for host in ("t.me", "telegram.me"):
        request = urllib.request.Request(
            f"https://{host}/s/{channel}",
            headers={
                "User-Agent": "Mozilla/5.0 dicodePing-Scanner/1.6.0",
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(2 * 1024 * 1024)
                charset = response.headers.get_content_charset() or "utf-8"
                page = body.decode(charset, errors="ignore")
                rows = extract_configs(page)
                if rows:
                    return rows[:18]
                errors.append(f"{host}: empty")
        except Exception as exc:
            errors.append(f"{host}: {exc}")
    return []


def collect_public_configs(
    stage: StageCallback | None = None,
    progress: ProgressCallback | None = None,
    *,
    maximum: int = 140,
) -> list[str]:
    if stage:
        stage("در حال دریافت کانفیگ‌های عمومی با اتصال داخلی برنامه...")
    collected: list[str] = []
    seen: set[str] = set()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_preview, channel): channel for channel in SCANNER_CHANNELS}
        for future in concurrent.futures.as_completed(futures):
            done += 1
            try:
                rows = future.result()
            except Exception:
                rows = []
            for raw in rows:
                key = normalize_key(raw)
                if not key or key in seen:
                    continue
                seen.add(key)
                collected.append(raw)
                if len(collected) >= maximum:
                    break
            if progress:
                progress(done, len(SCANNER_CHANNELS))
    return collected[:maximum]


def quality_from_measurements(ping_ms: int | None, samples: Iterable[int] = ()) -> tuple[int, str, int | None]:
    values = [int(value) for value in samples if int(value) > 0]
    jitter = int(round(pstdev(values))) if len(values) > 1 else None
    if ping_ms is None:
        return 0, "نامعتبر", jitter
    score = 100
    if ping_ms > 900:
        score -= 72
    elif ping_ms > 600:
        score -= 55
    elif ping_ms > 400:
        score -= 38
    elif ping_ms > 250:
        score -= 24
    elif ping_ms > 160:
        score -= 12
    if jitter is not None:
        score -= min(25, int(jitter * 0.45))
    score = max(1, min(100, score))
    label = "عالی" if score >= 85 else "خوب" if score >= 68 else "متوسط" if score >= 45 else "ضعیف"
    return score, label, jitter


def _probe_one(raw: str) -> tuple[str, int | None, tuple[int, ...]]:
    endpoint = parse_endpoint(raw)
    if not endpoint:
        return raw, None, ()
    # Fast endpoint gate prevents starting an Xray process for obviously dead hosts.
    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=1.35):
            pass
    except OSError:
        return raw, None, ()
    samples: list[int] = []
    for _ in range(2):
        value = probe_outbound_delay(raw, timeout=3.4)
        if value is not None:
            samples.append(int(value))
        if len(samples) == 1:
            time.sleep(0.08)
    return raw, int(round(median(samples))) if samples else None, tuple(samples)


def _quota_from_name(raw: str) -> SubscriptionUsage:
    # Raw config links do not have an authoritative quota API. This heuristic is
    # intentionally marked separately from subscription-userinfo metadata.
    decoded = urllib.parse.unquote(raw.rsplit("#", 1)[-1]) if "#" in raw else ""
    match = _TRAFFIC_RX.search(decoded)
    if not match:
        return SubscriptionUsage()
    amount = float(match.group(1))
    unit = match.group(2).upper()
    factor = {"MB": 1024**2, "GB": 1024**3, "TB": 1024**4}[unit]
    return SubscriptionUsage(total=int(amount * factor), status="limited", source="name-heuristic")


def scan_configs(
    service,
    name: str,
    bootstrap_raw: str = "",
    *,
    already_connected: bool = False,
    stage: StageCallback | None = None,
    progress: ProgressCallback | None = None,
) -> ScanSummary:
    started = time.monotonic()
    temporary = XrayManager()
    try:
        if not already_connected:
            if not bootstrap_raw:
                raise RuntimeError("برای شروع اسکن هیچ سرور داخلی آماده‌ای وجود ندارد")
            if stage:
                stage("در حال برقراری اتصال اولیه اسکنر...")
            temporary.start(bootstrap_raw, progress=stage, language="fa")
        raw_configs = collect_public_configs(stage, progress)
    finally:
        if not already_connected:
            temporary.stop()

    if not raw_configs:
        raise RuntimeError("اسکنر از منابع عمومی کانفیگ قابل استفاده‌ای دریافت نکرد")
    if stage:
        stage("اتصال اولیه قطع شد؛ در حال تست واقعی کانفیگ‌ها...")

    tested = 0
    alive: list[tuple[str, int, tuple[int, ...]]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_probe_one, raw): raw for raw in raw_configs}
        for future in concurrent.futures.as_completed(futures):
            tested += 1
            try:
                raw, ping, samples = future.result()
            except Exception:
                raw, ping, samples = futures[future], None, ()
            if ping is not None:
                alive.append((raw, ping, samples))
            if progress:
                progress(tested, len(raw_configs))

    if not alive:
        raise RuntimeError("هیچ کانفیگ پاسخ‌گو پیدا نشد؛ اتصال یا محدودیت شبکه را بررسی کنید")
    alive.sort(key=lambda item: item[1])
    alive = alive[:80]

    source_id = "scanner-" + sha256(f"{name}:{time.time_ns()}".encode()).hexdigest()[:12]
    source = SourceDefinition(
        id=source_id,
        name=(name.strip() or "اسکن دیکد")[:48],
        url=f"dicode://scanner/{source_id}",
        order=999,
        enabled=False,
        is_default=False,
    )

    endpoints = [(raw, parse_endpoint(raw), ping, samples) for raw, ping, samples in alive]
    ip_map = {endpoint.host: resolve_ipv4(endpoint.host) for _, endpoint, _, _ in endpoints if endpoint}
    if stage:
        stage("در حال تکمیل کیفیت و موقعیت سرورها...")
    geo_map = service.geo.resolve_many([ip for ip in ip_map.values() if ip])
    records: list[ServerRecord] = []
    for index, (raw, endpoint, ping, samples) in enumerate(endpoints, start=1):
        if not endpoint:
            continue
        ip = ip_map.get(endpoint.host, "")
        geo = geo_map.get(ip, {})
        country = str(geo.get("country") or "نامشخص")
        display_name = f"{source.name} • {index:02d}"
        quality_score, quality_label, jitter = quality_from_measurements(ping, samples)
        quota = _quota_from_name(raw)
        clean_raw = set_display_name(raw, display_name)
        records.append(
            ServerRecord(
                id=record_id(raw), name=display_name, protocol=endpoint.protocol.upper(),
                host=endpoint.host, port=endpoint.port, config_blob=config_to_blob(clean_raw),
                ping_ms=ping, ip=ip, country=country,
                country_code=str(geo.get("country_code") or "").upper(),
                region=str(geo.get("region") or ""), city=str(geo.get("city") or ""),
                isp=str(geo.get("isp") or ""), asn=str(geo.get("asn") or ""),
                geo_provider=str(geo.get("geo_provider") or ""),
                geo_confidence=str(geo.get("geo_confidence") or ""),
                source_id=source.id, source_name=source.name, source_order=source.order,
                status="online", favorite=False, last_checked=utc_now(), failures=0,
                quality_score=quality_score, quality_label=quality_label, jitter_ms=jitter,
                quota_total_bytes=quota.total, quota_used_bytes=quota.used,
                quota_expire_at=quota.expire, quota_status=quota.status,
                quota_source=quota.source,
            )
        )

    previous = [row for row in service.store.load_servers() if row.source_id != source.id]
    merged_by_id = {row.id: row for row in previous}
    for row in records:
        merged_by_id[row.id] = row
    merged = list(merged_by_id.values())
    merged.sort(key=lambda row: (row.ping_ms is None, row.ping_ms or 999999, row.name.casefold()))
    service.store.save_servers(merged[:320])
    return ScanSummary(source, records, len(raw_configs), tested, int(time.monotonic() - started))


def parse_subscription_userinfo(value: str | None) -> SubscriptionUsage:
    if not value:
        return SubscriptionUsage()
    fields: dict[str, int] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        try:
            fields[key.strip().lower()] = max(0, int(float(raw.strip())))
        except ValueError:
            continue
    total = fields.get("total", 0)
    expire = fields.get("expire", 0)
    used = fields.get("upload", 0) + fields.get("download", 0)
    now = int(time.time())
    status = "expired" if expire and expire <= now else "limited" if total > 0 else "unlimited" if value else "unknown"
    return SubscriptionUsage(
        upload=fields.get("upload", 0), download=fields.get("download", 0),
        total=total, expire=expire, status=status, source="subscription-userinfo",
    )


def fetch_subscription_usage(url: str, timeout: float = 9.0) -> SubscriptionUsage:
    if not url.lower().startswith(("http://", "https://")):
        return SubscriptionUsage()
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "dicodePing/1.6.0", "Range": "bytes=0-2047"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            usage = parse_subscription_userinfo(response.headers.get("subscription-userinfo"))
            if usage.status != "unknown":
                return usage
            # Several panels expose the same values as individual headers.
            synthetic = ";".join(
                f"{key}={response.headers.get('profile-' + key, '')}"
                for key in ("upload", "download", "total", "expire")
            )
            return parse_subscription_userinfo(synthetic)
    except Exception:
        return SubscriptionUsage()


def enrich_usage_and_quality(records: list[ServerRecord], sources: list[SourceDefinition]) -> list[ServerRecord]:
    by_source = {source.id: source for source in sources}
    source_ids = sorted({row.source_id for row in records})
    usage_map: dict[str, SubscriptionUsage] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(source_ids)))) as executor:
        futures = {
            executor.submit(fetch_subscription_usage, by_source[source_id].url): source_id
            for source_id in source_ids
            if source_id in by_source
        }
        for future, source_id in [(future, source_id) for future, source_id in futures.items()]:
            try:
                usage_map[source_id] = future.result()
            except Exception:
                usage_map[source_id] = SubscriptionUsage()

    enriched: list[ServerRecord] = []
    for row in records:
        score, label, jitter = quality_from_measurements(row.ping_ms, ())
        usage = usage_map.get(row.source_id, SubscriptionUsage())
        heuristic = _quota_from_name(row.name)
        if usage.status == "unknown" and heuristic.status != "unknown":
            usage = heuristic
        row.quality_score = score
        row.quality_label = label
        row.jitter_ms = row.jitter_ms if row.jitter_ms is not None else jitter
        row.quota_total_bytes = usage.total
        row.quota_used_bytes = usage.used
        row.quota_expire_at = usage.expire
        row.quota_status = usage.status
        row.quota_source = usage.source
        enriched.append(row)
    return enriched
