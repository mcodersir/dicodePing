"""dicodePing one-click scanner — v1.6.0-rc.2 rewrite.

This is the second iteration of the scanner.  The first iteration (rc.1)
only re-fetched the program's own default subscription.  This rewrite
does what the user actually asked for: it crawls Telegram channels
(exactly like DicodeConfigChecker's stage 1) using the program's own
running VPN, real-proxy-probes every candidate, drops the unresponsive
ones, and stores the survivors as a **brand new user source** that
appears next to the primary source on the Servers page.

User-visible behaviour
----------------------
1.  User opens the Scanner page and taps the single primary button.
2.  The scanner crawls the bundled Telegram channel list in parallel.
3.  Every unique config URI is real-proxy-probed (start a tiny xray
    instance with a SOCKS inbound, issue one HTTP request through it,
    measure the delay — exactly like the existing ping pipeline).
4.  Servers that did not respond are dropped.
5.  Survivors are saved into a new source whose name the user can
    customise (default: ``اسکنر <date>``).  The new source appears as
    a new tab on the Servers page, next to the primary source.
6.  The full subscription is also stored internally so the user can copy
    every server URI in one click (plain text or Base64).

All tunable settings (concurrency, timeouts, retry budget, max server
count) live in this file on purpose — the user explicitly asked for
the configuration to live in the code, not the UI.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .constants import DATA_DIR, MAX_DISCOVERY_CONFIGS
from .crawler import crawl_telegram_channels, load_channels
from .diagnostics import get_logger
from .i18n import tr
from .models import DiscoveredConfig, ServerRecord, SourceDefinition, utc_now
from .protocols import (
    b64_encode_text,
    config_to_blob,
    normalize_key,
    parse_endpoint,
    record_id,
    set_display_name,
)
from .sources import source_id_for_url
from .storage import JsonStore

LOGGER = get_logger("scanner")

# --- Hard-coded fast scanner profile -------------------------------------
SCAN_CRAWL_WORKERS = 8          # parallel Telegram channel fetches
SCAN_CRAWL_TIMEOUT_S = 12.0     # per-channel HTTP timeout
SCAN_PER_CHANNEL_LIMIT = 30     # max configs to keep per channel
SCAN_PROBE_WORKERS = 32         # parallel real-tunnel probes
SCAN_PROBE_TIMEOUT_S = 4.0      # max wait for a single proxy delay probe
SCAN_PROBE_RETRY_LIMIT = 4      # how many failed servers to retry once
SCAN_PROBE_RETRY_WORKERS = 8
SCAN_MAX_SERVERS = 240          # cap the produced sub size
# -------------------------------------------------------------------------

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]


@dataclass
class ScannerResult:
    """Public snapshot returned to the UI thread when the scan completes."""

    sub_name: str
    source_id: str
    servers: list[ServerRecord]
    raw_lines: list[str]
    base64_payload: str
    duration_seconds: float
    downloaded: int
    dropped: int


# --- Internal scanner-sub persistence -----------------------------------
# We persist every successful scan as a custom source in the regular
# settings["sources"] list, so the new sub shows up on the Servers page
# as a brand new tab — exactly like the primary source.

SCANNER_HISTORY_FILE = DATA_DIR / "scanner_history.json"


def _load_history() -> list[dict]:
    try:
        import json
        return json.loads(SCANNER_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(rows: list[dict]) -> None:
    import json
    SCANNER_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCANNER_HISTORY_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def list_scanner_subs() -> list[dict]:
    """Return previously saved scanner subs (newest first)."""
    return list(reversed(_load_history()))


def generate_sub_name(custom: str | None = None) -> str:
    """Auto-generate a friendly Persian name, or use the user's custom name."""
    if custom and custom.strip():
        return custom.strip()
    now = datetime.now()
    return f"اسکنر • {now.strftime('%Y/%m/%d %H:%M')}"


# --- Probing ------------------------------------------------------------

def _probe_one(
    raw_config: str,
    *,
    timeout: float = SCAN_PROBE_TIMEOUT_S,
) -> int | None:
    """Run a single real-tunnel proxy delay probe and return milliseconds.

    Re-uses the existing ``probe_outbound_delay`` helper so the scanner
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


# --- Main entry point ---------------------------------------------------

def run_scan(
    *,
    store: JsonStore,
    language: str = "fa",
    custom_name: str | None = None,
    stage: StageCallback | None = None,
    crawl_progress: ProgressCallback | None = None,
    probe_progress: ProgressCallback | None = None,
) -> ScannerResult:
    """Execute a one-click scan and persist the result.

    The function is synchronous and intended to run inside a worker
    thread (see ``ScannerThread`` in workers.py).
    """
    started = time.monotonic()

    def _st(text: str) -> None:
        if stage:
            stage(text)

    # 1) Crawl Telegram channels.
    _st(tr(language, "scanner_crawl"))
    channels = load_channels()
    if not channels:
        raise RuntimeError(
            "لیست کانال‌های تلگرام یافت نشد؛ بسته‌بندی برنامه ناقص است."
            if language != "en"
            else "Telegram channel list is missing; the build is incomplete."
        )
    LOGGER.info("Scanner: crawling %d Telegram channels", len(channels))

    raw_configs = crawl_telegram_channels(
        channels=channels,
        per_channel_limit=SCAN_PER_CHANNEL_LIMIT,
        max_workers=SCAN_CRAWL_WORKERS,
        timeout=SCAN_CRAWL_TIMEOUT_S,
        progress=lambda done, total, ch: (
            crawl_progress(done, total) if crawl_progress else None,
        ),
    )
    if not raw_configs:
        raise RuntimeError(
            "هیچ کانفیگی از کانال‌های تلگرام دریافت نشد. ابتدا از طریق منبع اصلی به یک سرور وصل شوید، سپس اسکن را دوباره امتحان کنید."
            if language != "en"
            else "No configs were collected from Telegram channels. Connect to a server via the primary source first, then try the scan again."
        )

    # 2) Deduplicate and cap.
    seen: set[str] = set()
    unique: list[str] = []
    for raw in raw_configs:
        key = normalize_key(raw)
        if key in seen:
            continue
        seen.add(key)
        unique.append(raw)
        if len(unique) >= MAX_DISCOVERY_CONFIGS:
            break
    LOGGER.info("Scanner: %d unique configs after dedup", len(unique))

    # 3) Real-proxy probe each candidate.
    _st(tr(language, "scanner_probing"))
    total = len(unique)
    if probe_progress:
        probe_progress(0, total)

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
            if probe_progress:
                probe_progress(completed, total)
            if ping_ms is not None:
                alive.append((raw, ping_ms))

    # 4) Retry a few failures once.
    if total - len(alive) > 0 and SCAN_PROBE_RETRY_LIMIT > 0:
        alive_keys = {a[0] for a in alive}
        retried = [raw for raw in unique if raw not in alive_keys][:SCAN_PROBE_RETRY_LIMIT]
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

    # 6) Build ServerRecord rows.
    _st(tr(language, "scanner_saving"))
    sub_name = generate_sub_name(custom_name)
    source_id = "scanner-" + hashlib.sha1(sub_name.encode("utf-8")).hexdigest()[:10]
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
                source_id=source_id,
                source_name=sub_name,
                source_order=0,
                status="online",
                favorite=False,
                last_checked=utc_now(),
                last_connected="",
                failures=0,
            )
        )

    # 7) Persist as a new user source so it shows up on the Servers page.
    raw_lines = [set_display_name(raw, "") for raw, _ in alive]
    base64_payload = b64_encode_text("\n".join(raw_lines))

    try:
        settings = store.load_settings()
        sources_list = list(settings.get("sources") or [])
        # Remove any previous scanner source with the same id (re-scan
        # overwrites the same name slot).
        sources_list = [s for s in sources_list if not (isinstance(s, dict) and s.get("id") == source_id)]
        # Append the new scanner source.
        sources_list.append(
            SourceDefinition(
                id=source_id,
                name=sub_name,
                url="",  # scanner subs have no remote URL; they live locally
                order=len(sources_list),
                enabled=True,
                is_default=False,
            ).to_dict()
        )
        settings["sources"] = sources_list
        store.save_settings(settings)
    except Exception:
        LOGGER.exception("Scanner: failed to persist new source in settings")

    # 8) Save the scanner history record (for copy-all + UI history list).
    history_record = {
        "name": sub_name,
        "source_id": source_id,
        "created_at": utc_now(),
        "servers": [r.to_dict() for r in records],
        "raw_lines": raw_lines,
        "base64": base64_payload,
        "downloaded": total,
        "dropped": max(0, total - len(records)),
        "duration_seconds": time.monotonic() - started,
    }
    history = _load_history()
    # Replace any previous entry with the same source_id.
    history = [h for h in history if h.get("source_id") != source_id]
    history.append(history_record)
    if len(history) > 12:
        history = history[-12:]
    _save_history(history)

    # 9) Merge survivors into the main server store so the user can
    #    immediately connect to them from the Servers page.
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
        "Scanner: completed in %.1fs — crawled=%d alive=%d dropped=%d",
        duration, total, len(records), max(0, total - len(records)),
    )

    return ScannerResult(
        sub_name=sub_name,
        source_id=source_id,
        servers=records,
        raw_lines=raw_lines,
        base64_payload=base64_payload,
        duration_seconds=duration,
        downloaded=total,
        dropped=max(0, total - len(records)),
    )


# --- Copy / export helpers ----------------------------------------------

def export_subscription(sub_name: str, *, as_base64: bool = False) -> str:
    """Return the saved scanner sub as a plain text or base64 payload."""
    rows = _load_history()
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
    rows = _load_history()
    rows = [row for row in rows if row.get("name") != sub_name]
    _save_history(rows)
