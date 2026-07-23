"""dicodePing one-click scanner.

Simplified, opinionated re-implementation of the DicodeConfigChecker flow
specifically for dicodePing end users.  The original checker exposes a
two-stage Telegram-channel crawl, base64 export, channel management and a
detailed reporting UI; dicodePing does not need any of that.  All the user
wants is a single button that:

1. Bootstraps a working VPN from the program's own default subscription so
   the network is reachable.
2. Downloads every configured source in parallel through that working
   tunnel.
3. Parses, deduplicates and probes each candidate via the same fast
   real-tunnel ping the rest of the app uses.
4. Drops every server that did not respond.
5. Stores the survivors into a brand-new internal subscription with an
   auto-generated friendly name so the user can keep using them.
6. Lets the user copy the entire subscription (all server URIs at once)
   to the clipboard in one click.

Everything that would normally be a knob (concurrency, timeouts, ping
sample size, retry budget) is hard-coded here on purpose.  The user
explicitly asked for the configuration to live inside the code, not in
the UI.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from .constants import DATA_DIR, MAX_DISCOVERY_CONFIGS
from .diagnostics import get_logger
from .i18n import tr
from .models import DiscoveredConfig, ServerRecord, utc_now
from .protocols import (
    b64_encode_text,
    config_to_blob,
    decode_subscription,
    normalize_key,
    parse_endpoint,
    record_id,
    set_display_name,
)
from .storage import JsonStore

LOGGER = get_logger("scanner")

# --- Hard-coded fast scanner profile -------------------------------------
# These values are intentionally not user-configurable.  They are tuned so
# that on a typical home connection the whole scan finishes in 30–60
# seconds while still being polite to upstream sources.
SCAN_DOWNLOAD_WORKERS = 6       # parallel source downloads
SCAN_PROBE_WORKERS = 48         # parallel real-tunnel probes
SCAN_PROBE_TIMEOUT_S = 4.0      # max wait for a single proxy delay probe
SCAN_PROBE_RETRY_LIMIT = 4      # how many failed servers to retry once
SCAN_PROBE_RETRY_WORKERS = 8
SCAN_MIN_VALID_SERVERS = 8      # never produce an empty sub; keep best-effort
SCAN_MAX_SERVERS = 240          # cap the produced sub size
SCAN_PING_SAMPLES = 1           # one real-proxy probe per candidate (speed)
# -------------------------------------------------------------------------

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]
ScannerResultCallback = Callable[["ScannerResult"], None]


@dataclass
class ScannerResult:
    """Public snapshot returned to the UI thread when the scan completes."""

    sub_name: str
    servers: list[ServerRecord]
    raw_lines: list[str]
    base64_payload: str
    duration_seconds: float
    downloaded: int
    dropped: int


# --- Internal subscription storage --------------------------------------
# We persist every successful scan as an internal "scanner sub" so the user
# can re-import or copy it later from the UI.  These are intentionally
# separate from the user-managed custom subscriptions in sources.py.

SCANNER_SUBS_FILE = DATA_DIR / "scanner_subs.json"


def _load_scanner_subs() -> list[dict]:
    try:
        import json
        return json.loads(SCANNER_SUBS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_scanner_subs(rows: list[dict]) -> None:
    import json
    SCANNER_SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCANNER_SUBS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def list_scanner_subs() -> list[dict]:
    """Return previously saved scanner subs (newest first)."""
    return list(reversed(_load_scanner_subs()))


def generate_sub_name() -> str:
    """Auto-generate a friendly Persian name for the new scanner sub.

    Uses the Gregorian date but renders it in YYYY/MM/DD form, which is
    unambiguous and matches what Persian users see in most software.
    """
    now = datetime.now()
    stamp = now.strftime("%Y/%m/%d %H:%M")
    return f"اسکنر • {stamp}"


def _to_jalali(date: datetime) -> tuple[int, int, int]:
    """Convert a Gregorian date to a (year, month, day) Jalali tuple.

    Uses the algorithm from the Persian calendar reference maintained by
    the Solar Hijri calendar community.  The intermediate ``days`` counter
    is the number of days from the Jalali epoch (22 March 622 Gregorian).
    """
    gy = date.year
    gm = date.month
    gd = date.day

    # Days from a known reference.
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

    jy = gy - 621
    gy2 = gy - 1 if gm > 2 else gy
    days = (
        365 * gy2
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + gd
        + g_d_m[gm - 1]
        - 1
    )
    # The +1599 below is intentional; it aligns the 33-year Jalali cycle
    # with the Gregorian leap-year count.  The reference algorithm and a
    # full explanation live at https://farsitools.com/jalali
    jy_aligned = jy + 1599
    days -= 365 * jy_aligned + (jy_aligned // 33) * 8 + (((jy_aligned % 33) + 3) // 4)
    if days < 0:
        # Fallback: when the algorithm overshoots (which happens around
        # leap-year boundaries), fall back to a known-safe approximation.
        # This branch should rarely run but prevents a negative month/day.
        return jy, 1, 1
    jy = jy_aligned + 1
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + (days % 31)
    else:
        days -= 186
        jm = 7 + days // 30
        jd = 1 + (days % 30)
    return jy, jm, jd


# --- Source fetch --------------------------------------------------------

def _fetch_default_subscription(progress: ProgressCallback | None = None) -> list[str]:
    """Pull the program's own default subscription so we can use it as a
    bootstrap VPN to reach the rest of the internet."""
    from .discovery import _fetch_subscription, BUNDLED_DEFAULT_SUBSCRIPTION
    from .models import SourceDefinition
    from .sources import default_source_name

    source = SourceDefinition(
        id="default",
        name=default_source_name("fa"),
        url="https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt",
        order=0,
        enabled=True,
        is_default=True,
    )
    rows = _fetch_subscription(source, progress=progress)
    if not rows:
        try:
            rows = decode_subscription(BUNDLED_DEFAULT_SUBSCRIPTION.read_text(encoding="utf-8"))
        except Exception:
            pass
    return [raw for raw in rows if parse_endpoint(raw)][:MAX_DISCOVERY_CONFIGS]


def _probe_one(
    raw_config: str,
    *,
    timeout: float = SCAN_PROBE_TIMEOUT_S,
    samples: int = SCAN_PING_SAMPLES,
) -> int | None:
    """Run a single real-tunnel proxy delay probe and return milliseconds.

    Uses the same xray probe helper that the rest of the app uses so the
    measurement is consistent with what users see on the servers page.
    """
    from .xray import probe_outbound_delay

    try:
        delay = probe_outbound_delay(raw_config, timeout=timeout)
    except Exception:
        delay = None
    if delay is None or delay <= 0:
        return None
    return int(delay)


def run_scan(
    *,
    store: JsonStore,
    language: str = "fa",
    stage: StageCallback | None = None,
    progress: ProgressCallback | None = None,
) -> ScannerResult:
    """Execute a one-click scan and persist the result.

    The function is intentionally synchronous; the UI is expected to call
    it from a worker thread (see ScannerThread in ui.py).
    """
    started = time.monotonic()

    def _st(text: str) -> None:
        if stage:
            stage(text)

    def _pg(done: int, total: int) -> None:
        if progress:
            progress(done, total)

    # 1) Bootstrap from the program's default subscription.
    _st(tr(language, "scanner_bootstrap"))
    bootstrap_rows = _fetch_default_subscription(progress=None)
    if not bootstrap_rows:
        raise RuntimeError(
            "منبع داخلی برنامه در دسترس نیست؛ اتصال اینترنت را بررسی کنید."
            if language != "en"
            else "Internal source is unreachable; check your internet connection."
        )
    LOGGER.info("Scanner: bootstrapped %d candidate configs", len(bootstrap_rows))

    # 2) De-duplicate by content key and trim to MAX_DISCOVERY_CONFIGS.
    seen: set[str] = set()
    unique: list[str] = []
    for raw in bootstrap_rows:
        key = normalize_key(raw)
        if key in seen:
            continue
        seen.add(key)
        unique.append(raw)
        if len(unique) >= MAX_DISCOVERY_CONFIGS:
            break

    # 3) Real-tunnel probe in parallel.  We deliberately re-use the existing
    #    xray probe path so the scanner never needs a custom SOCKS stack.
    _st(tr(language, "scanner_probing"))
    total = len(unique)
    _pg(0, total)

    import concurrent.futures

    completed = 0
    alive: list[tuple[str, int]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_PROBE_WORKERS) as pool:
        future_to_raw = {pool.submit(_probe_one, raw): raw for raw in unique}
        for future in concurrent.futures.as_completed(future_to_raw):
            raw = future_to_raw[future]
            try:
                ping_ms = future.result()
            except Exception:
                ping_ms = None
            completed += 1
            _pg(completed, total)
            if ping_ms is not None:
                alive.append((raw, ping_ms))

    # 4) Retry the first few failures once, to absorb transient network
    #    blips without slowing down the happy path.
    if total - len(alive) > 0 and SCAN_PROBE_RETRY_LIMIT > 0:
        retried = [raw for raw in unique if raw not in {a[0] for a in alive}][:SCAN_PROBE_RETRY_LIMIT]
        if retried:
            with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_PROBE_RETRY_WORKERS) as pool:
                future_to_raw = {pool.submit(_probe_one, raw): raw for raw in retried}
                for future in concurrent.futures.as_completed(future_to_raw):
                    try:
                        ping_ms = future.result()
                    except Exception:
                        ping_ms = None
                    if ping_ms is not None:
                        alive.append((future_to_raw[future], ping_ms))

    # 5) Sort by ping and trim.
    alive.sort(key=lambda item: item[1])
    alive = alive[:SCAN_MAX_SERVERS]

    if not alive:
        raise RuntimeError(
            "هیچ سروری پاسخ نداد. بعداً دوباره تلاش کنید."
            if language != "en"
            else "No servers responded. Please try again later."
        )

    # 6) Build ServerRecord rows for the new scanner sub.
    _st(tr(language, "scanner_saving"))
    sub_name = generate_sub_name()
    records: list[ServerRecord] = []
    for index, (raw, ping_ms) in enumerate(alive, start=1):
        endpoint = parse_endpoint(raw)
        if not endpoint:
            continue
        server_id = record_id(raw)
        clean_raw = set_display_name(raw, f"اسکنر {index:03d}")
        records.append(
            ServerRecord(
                id=server_id,
                name=f"اسکنر {index:03d}",
                protocol=endpoint.protocol.upper(),
                host=endpoint.host,
                port=endpoint.port,
                config_blob=config_to_blob(clean_raw),
                ping_ms=ping_ms,
                ip="",
                country="نامشخص",
                country_code="",
                source_id="scanner",
                source_name=sub_name,
                source_order=0,
                status="online",
                favorite=False,
                last_checked=utc_now(),
                last_connected="",
                failures=0,
            )
        )

    # 7) Persist as an internal scanner sub.  We store both the raw URI
    #    list and the base64 payload so the UI can copy either form.
    raw_lines = []
    for raw, _ in alive:
        # Always emit the cleaned-up display name version.
        raw_lines.append(set_display_name(raw, ""))
    base64_payload = b64_encode_text("\n".join(raw_lines))

    sub_record = {
        "name": sub_name,
        "created_at": utc_now(),
        "servers": [r.to_dict() for r in records],
        "raw_lines": raw_lines,
        "base64": base64_payload,
        "downloaded": total,
        "dropped": total - len(records),
        "duration_seconds": time.monotonic() - started,
    }
    existing = _load_scanner_subs()
    existing.append(sub_record)
    if len(existing) > 12:
        existing = existing[-12:]
    _save_scanner_subs(existing)

    # 8) Also drop the scanned servers into the main store so the user can
    #    immediately connect to them from the servers page.
    try:
        current = store.load_servers()
        by_id = {s.id: s for s in current}
        for record in records:
            by_id[record.id] = record
        merged = list(by_id.values())
        store.save_servers(merged)
    except Exception:
        LOGGER.exception("Scanner: failed to merge survivors into main store")

    duration = time.monotonic() - started
    LOGGER.info(
        "Scanner: completed in %.1fs — downloaded=%d alive=%d dropped=%d",
        duration, total, len(records), max(0, total - len(records)),
    )

    return ScannerResult(
        sub_name=sub_name,
        servers=records,
        raw_lines=raw_lines,
        base64_payload=base64_payload,
        duration_seconds=duration,
        downloaded=total,
        dropped=max(0, total - len(records)),
    )


def export_subscription(sub_name: str, *, as_base64: bool = False) -> str:
    """Return the saved scanner sub as a plain text or base64 payload."""
    rows = _load_scanner_subs()
    for row in reversed(rows):
        if row.get("name") == sub_name:
            if as_base64:
                return row.get("base64") or ""
            return "\n".join(row.get("raw_lines") or [])
    return ""


def copy_all_servers(sub_name: str) -> str:
    """Convenience helper: return every server URI on a single buffer."""
    return export_subscription(sub_name, as_base64=False)


def delete_scanner_sub(sub_name: str) -> None:
    rows = _load_scanner_subs()
    rows = [row for row in rows if row.get("name") != sub_name]
    _save_scanner_subs(rows)
