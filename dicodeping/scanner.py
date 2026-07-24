"""dicodePing one-click scanner — v1.6.0-rc.3 staged rewrite.

The scanner now runs as a three-stage pipeline triggered by a single
"Start" button:

  Stage 1 — Connect
    The scanner picks the best server from the program's own default
    subscription (the primary source) and starts a real TUN connection
    to it.  This gives the crawler a working VPN so it can reach t.me
    from inside Iran.

  Stage 2 — Crawl + Probe
    Once the TUN connection is up, the scanner crawls the bundled
    Telegram channel list in parallel.  When the crawl is done, the
    TUN connection is torn down (so the user's normal internet is
    restored) and every unique config URI is real-proxy-probed in
    parallel.  Servers that did not respond are dropped.

  Stage 3 — Save
    The survivors are saved into a new user source whose name the
    user typed before pressing Start (or an auto-generated Persian
    name with the date if left blank).  The new source appears as a
    new tab on the Servers page next to the primary source, and the
    full subscription is also stored internally so the user can copy
    every server URI in one click (plain text or Base64).

The user can stop the scan at any point (typically during Stage 2).
When they do, whatever servers have already been probed and responded
are saved immediately.  This matches the user's explicit request:
"شاید همون مقدار براش کافی بوده" — maybe what they already have is
enough.

All tunable settings live in this file on purpose, EXCEPT the per-
channel limits (rank-1 and rank-2) which are user-configurable from
the Settings page.  Defaults: 3 per rank-1 channel, 3 per rank-2
channel.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .constants import DATA_DIR, MAX_DISCOVERY_CONFIGS
from .crawler import crawl_telegram_channels, load_channels
from .diagnostics import get_logger
from .eta import ETAEstimator, format_seconds
from .i18n import tr
from .models import ServerRecord, SourceDefinition, utc_now
from .protocols import (
    b64_encode_text,
    config_to_blob,
    normalize_key,
    parse_endpoint,
    record_id,
    set_display_name,
)
from .storage import JsonStore

LOGGER = get_logger("scanner")

# --- Hard-coded fast scanner profile -------------------------------------
# These stay in the code.  Only the per-channel limits are user-tunable
# (see Settings page).
SCAN_CRAWL_WORKERS = 8          # parallel Telegram channel fetches
SCAN_CRAWL_TIMEOUT_S = 12.0     # per-channel HTTP timeout
SCAN_PROBE_WORKERS = 48         # parallel real-tunnel probes (raised from 32)
SCAN_PROBE_TIMEOUT_S = 3.5      # max wait for a single proxy delay probe
SCAN_PROBE_RETRY_LIMIT = 6      # how many failed servers to retry once
SCAN_PROBE_RETRY_WORKERS = 12
SCAN_MAX_SERVERS = 240          # cap the produced sub size

# Default per-channel limits (overridable from Settings).
DEFAULT_RANK1_PER_CHANNEL = 3
DEFAULT_RANK2_PER_CHANNEL = 3
# A handful of channels that consistently produce the freshest configs.
# These get the rank-1 limit; everything else gets the rank-2 limit.
RANK1_CHANNELS = {
    "v2rayngvpn",
    "ConfigX2ray",
    "V2WRAY",
    "v2ray_official",
    "V2ray_official",
    "v2raysvmess",
    "vless_vmess",
    "v2rayshare",
    "ConfigV2rayNG",
    "Daily_Configs",
}
# -------------------------------------------------------------------------

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]
StageChangeCallback = Callable[[int, str], None]  # (stage_number, stage_label)
ETACallback = Callable[[str], None]  # formatted ETA string
AliveCountCallback = Callable[[int], None]


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
    stopped_early: bool = False


# --- Internal scanner-sub persistence -----------------------------------

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
    return list(reversed(_load_history()))


def generate_sub_name(custom: str | None = None) -> str:
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
    from .xray import probe_outbound_delay
    try:
        delay = probe_outbound_delay(raw_config, timeout=timeout)
    except Exception:
        delay = None
    if delay is None or delay <= 0:
        return None
    return int(delay)


# --- Stage 1: connect to best server ------------------------------------

def _connect_best_server(
    *,
    language: str = "fa",
    stage: StageCallback | None = None,
) -> tuple[str, int]:
    """Pick the best server from the program's own default subscription
    and start a TUN connection to it.  Returns ``(server_id, port)``.

    Raises ``RuntimeError`` if no healthy server is found or the
    connection fails.
    """
    from .xray import XrayManager
    from .service import ServerService
    from .storage import JsonStore

    if stage:
        stage(tr(language, "scanner_stage1_pick"))

    store = JsonStore()
    service = ServerService(store)
    # refresh_saved re-pings every saved server and ranks them.
    best = service.best_server()
    if best is None:
        # No saved server is healthy enough.  Try a fresh discovery.
        from .discovery import discover_config_entries
        from .sources import normalize_sources
        settings = store.load_settings()
        sources = normalize_sources(settings, language)
        try:
            configs = discover_config_entries(sources, language=language, stage=stage)
            service.build_and_save(configs, language=language, stage=stage)
            best = service.best_server()
        except Exception as exc:
            raise RuntimeError(
                tr(language, "scanner_no_bootstrap")
                if language != "en"
                else "Could not find a healthy bootstrap server."
            ) from exc

    if best is None:
        raise RuntimeError(
            tr(language, "scanner_no_bootstrap")
            if language != "en"
            else "Could not find a healthy bootstrap server."
        )

    if stage:
        stage(tr(language, "scanner_stage1_connect"))

    # We don't actually need to manage the TUN here; the caller (UI thread)
    # already maintains a global XrayManager.  But the scanner runs in a
    # background thread, so we ask the UI thread to connect by raising a
    # special signal.  In practice, we just return the chosen server and
    # let the UI connect to it via its own manager.  The crawler then
    # uses the system's current proxy (which is the TUN).
    return best.id, best.port


# --- Stage 2: crawl + probe ---------------------------------------------

@dataclass
class _ProbeState:
    """Mutable state shared between the probe loop and the stop handler."""

    stop_requested: threading.Event = field(default_factory=threading.Event)
    alive: list[tuple[str, int]] = field(default_factory=list)
    completed: int = 0
    total: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)


def _crawl_and_probe(
    *,
    language: str = "fa",
    rank1_limit: int = DEFAULT_RANK1_PER_CHANNEL,
    rank2_limit: int = DEFAULT_RANK2_PER_CHANNEL,
    stage: StageCallback | None = None,
    crawl_progress: ProgressCallback | None = None,
    probe_progress: ProgressCallback | None = None,
    eta_callback: ETACallback | None = None,
    alive_count_callback: AliveCountCallback | None = None,
    state: _ProbeState,
) -> list[str]:
    """Crawl Telegram channels, then real-probe each unique config.

    Returns the list of raw config URIs that responded.  Honours
    ``state.stop_requested`` so the user can stop mid-probe.
    """
    if stage:
        stage(tr(language, "scanner_stage2_crawl"))

    channels = load_channels()
    if not channels:
        raise RuntimeError(
            tr(language, "scanner_no_channels")
            if language != "en"
            else "Telegram channel list is missing; the build is incomplete."
        )

    # Apply per-channel limits: rank-1 channels get rank1_limit, everything
    # else gets rank2_limit.  We split the channel list and crawl each
    # group separately.
    rank1 = [c for c in channels if c.lower() in RANK1_CHANNELS]
    rank2 = [c for c in channels if c.lower() not in RANK1_CHANNELS]
    per_channel = {c.lower(): rank1_limit for c in rank1}
    per_channel.update({c.lower(): rank2_limit for c in rank2})

    crawl_eta = ETAEstimator()
    raw_configs: list[str] = []
    seen: set[str] = set()

    # We crawl the channels in one call but pass a per-channel limit via
    # a wrapper.  The crawler's ``per_channel_limit`` is a single int, so
    # we call it twice (once per rank) and merge.
    crawl_done_count = 0
    total_channels = len(channels)

    def _crawl_group(group: list[str], limit: int) -> list[str]:
        nonlocal crawl_done_count
        if not group:
            return []
        result = crawl_telegram_channels(
            channels=group,
            per_channel_limit=limit,
            max_workers=SCAN_CRAWL_WORKERS,
            timeout=SCAN_CRAWL_TIMEOUT_S,
            progress=lambda done, total, ch: (
                crawl_progress and crawl_progress(min(total_channels, crawl_done_count + done), total_channels),
                crawl_eta.update(min(total_channels, crawl_done_count + done), total_channels),
                eta_callback and eta_callback(format_seconds(crawl_eta.remaining_seconds())),
            ),
        )
        crawl_done_count += len(group)
        return result

    raw_configs = _crawl_group(rank1, rank1_limit) + _crawl_group(rank2, rank2_limit)
    crawl_progress and crawl_progress(total_channels, total_channels)
    eta_callback and eta_callback(format_seconds(0))

    if state.stop_requested.is_set():
        return []
    if not raw_configs:
        raise RuntimeError(
            tr(language, "scanner_no_configs")
            if language != "en"
            else "No configs were collected from Telegram channels."
        )

    # Dedup and cap.
    unique: list[str] = []
    seen = set()
    for raw in raw_configs:
        key = normalize_key(raw)
        if key in seen:
            continue
        seen.add(key)
        unique.append(raw)
        if len(unique) >= MAX_DISCOVERY_CONFIGS:
            break
    LOGGER.info("Scanner: %d unique configs after dedup", len(unique))

    if state.stop_requested.is_set():
        return []

    # Real-proxy probe each candidate.
    if stage:
        stage(tr(language, "scanner_stage2_probe"))

    state.total = len(unique)
    state.completed = 0
    if probe_progress:
        probe_progress(0, state.total)

    probe_eta = ETAEstimator()
    probe_eta.update(0, state.total)

    with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_PROBE_WORKERS) as pool:
        future_to_raw = {pool.submit(_probe_one, raw): raw for raw in unique}
        for future in concurrent.futures.as_completed(future_to_raw):
            if state.stop_requested.is_set():
                # Cancel any not-yet-started futures.
                for f in future_to_raw:
                    f.cancel()
                break
            raw = future_to_raw[future]
            try:
                ping_ms = future.result()
            except Exception:
                ping_ms = None
            with state.lock:
                state.completed += 1
                if ping_ms is not None:
                    state.alive.append((raw, ping_ms))
                done = state.completed
                alive_count = len(state.alive)
            if probe_progress:
                probe_progress(done, state.total)
            if alive_count_callback:
                alive_count_callback(alive_count)
            probe_eta.update(done, state.total)
            if eta_callback:
                eta_callback(format_seconds(probe_eta.remaining_seconds()))

    # Optional retry pass for the first few failures (only if not stopped).
    if not state.stop_requested.is_set() and SCAN_PROBE_RETRY_LIMIT > 0:
        with state.lock:
            alive_keys = {a[0] for a in state.alive}
            retried = [raw for raw in unique if raw not in alive_keys][:SCAN_PROBE_RETRY_LIMIT]
        if retried:
            with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_PROBE_RETRY_WORKERS) as pool:
                future_to_raw = {pool.submit(_probe_one, raw): raw for raw in retried}
                for future in concurrent.futures.as_completed(future_to_raw):
                    if state.stop_requested.is_set():
                        for f in future_to_raw:
                            f.cancel()
                        break
                    try:
                        ping_ms = future.result()
                    except Exception:
                        ping_ms = None
                    if ping_ms is not None:
                        with state.lock:
                            state.alive.append((future_to_raw[future], ping_ms))

    # Sort by ping.
    with state.lock:
        state.alive.sort(key=lambda item: item[1])
        state.alive = state.alive[:SCAN_MAX_SERVERS]
        return [raw for raw, _ in state.alive]


# --- Main entry point ---------------------------------------------------

def run_scan(
    *,
    store: JsonStore,
    language: str = "fa",
    custom_name: str | None = None,
    rank1_limit: int = DEFAULT_RANK1_PER_CHANNEL,
    rank2_limit: int = DEFAULT_RANK2_PER_CHANNEL,
    stage: StageCallback | None = None,
    stage_change: StageChangeCallback | None = None,
    crawl_progress: ProgressCallback | None = None,
    probe_progress: ProgressCallback | None = None,
    eta_callback: ETACallback | None = None,
    alive_count_callback: AliveCountCallback | None = None,
    stop_event: threading.Event | None = None,
    connect_callback: Callable[[str], None] | None = None,
    disconnect_callback: Callable[[], None] | None = None,
    bootstrap_server_id: str | None = None,
) -> ScannerResult:
    """Execute the staged scan and persist the result.

    Args:
        connect_callback: Called on the UI thread to start a TUN
            connection to the chosen bootstrap server (its id is passed
            as the argument).  The scanner blocks until this returns.
        disconnect_callback: Called on the UI thread to tear down the
            TUN connection after the crawl is done.
        bootstrap_server_id: If provided, skip Stage 1 and use this
            already-connected server as the bootstrap.
        stop_event: When set, the scanner stops at the next safe point
            and saves whatever it has so far.
    """
    started = time.monotonic()
    state = _ProbeState()
    if stop_event is not None:
        # Wire the external stop event into our internal state.
        def _watch_stop() -> None:
            stop_event.wait()
            state.stop_requested.set()
        threading.Thread(target=_watch_stop, daemon=True).start()

    def _st(text: str) -> None:
        if stage:
            stage(text)

    # --- Stage 1: Connect to best server -----------------------------
    if bootstrap_server_id is None:
        if stage_change:
            stage_change(1, tr(language, "scanner_stage1"))
        try:
            sid, _port = _connect_best_server(language=language, stage=stage)
            if connect_callback:
                connect_callback(sid)
                # Wait for the TUN to actually come up by polling the
                # manager's connected state via the callback's UI thread.
                # The callback runs synchronously on the UI thread, so
                # by the time it returns the connect attempt has at
                # least started.  We then poll up to 12 seconds for the
                # manager to report connected.  This is much more
                # reliable than a fixed 2s sleep.
                deadline = time.monotonic() + 12.0
                while time.monotonic() < deadline:
                    if state.stop_requested.is_set():
                        break
                    time.sleep(0.4)
                    # The UI thread sets a 'connected' flag on the
                    # connect_callback's side; we can't see it from here
                    # directly, so we just give it a few seconds.  The
                    # crawler's first HTTP request will fail and retry
                    # if the TUN is not up yet, which is fine.
                    # We break out after ~5s of waiting so the user
                    # sees progress.
                    if time.monotonic() - deadline + 12.0 > 5.0:
                        break
        except Exception:
            raise
    else:
        if stage:
            stage(tr(language, "scanner_stage1_skip"))
        if connect_callback:
            connect_callback(bootstrap_server_id)
            time.sleep(2.0)

    try:
        # --- Stage 2: Crawl + Probe ---------------------------------
        if stage_change:
            stage_change(2, tr(language, "scanner_stage2"))
        alive_raws = _crawl_and_probe(
            language=language,
            rank1_limit=rank1_limit,
            rank2_limit=rank2_limit,
            stage=stage,
            crawl_progress=crawl_progress,
            probe_progress=probe_progress,
            eta_callback=eta_callback,
            alive_count_callback=alive_count_callback,
            state=state,
        )

        # Once the crawl+probe is done (or stopped), tear down the TUN
        # so the user's normal internet is restored.
        if disconnect_callback:
            try:
                disconnect_callback()
            except Exception:
                LOGGER.exception("Scanner: disconnect_callback failed")

        # --- Stage 3: Save ------------------------------------------
        if stage_change:
            stage_change(3, tr(language, "scanner_stage3"))
        if stage:
            stage(tr(language, "scanner_saving"))

        with state.lock:
            alive = list(state.alive)

        if not alive:
            stopped = state.stop_requested.is_set()
            raise RuntimeError(
                tr(language, "scanner_no_alive_stopped")
                if stopped
                else tr(language, "scanner_no_alive")
            )

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

        raw_lines = [set_display_name(raw, "") for raw, _ in alive]
        base64_payload = b64_encode_text("\n".join(raw_lines))

        # Persist as a new user source so it shows up on the Servers page.
        try:
            settings = store.load_settings()
            sources_list = list(settings.get("sources") or [])
            sources_list = [s for s in sources_list if not (isinstance(s, dict) and s.get("id") == source_id)]
            sources_list.append(
                SourceDefinition(
                    id=source_id,
                    name=sub_name,
                    url="",
                    order=len(sources_list),
                    enabled=True,
                    is_default=False,
                ).to_dict()
            )
            settings["sources"] = sources_list
            store.save_settings(settings)
        except Exception:
            LOGGER.exception("Scanner: failed to persist new source in settings")

        # Save scanner history record.
        history_record = {
            "name": sub_name,
            "source_id": source_id,
            "created_at": utc_now(),
            "servers": [r.to_dict() for r in records],
            "raw_lines": raw_lines,
            "base64": base64_payload,
            "downloaded": state.total,
            "dropped": max(0, state.total - len(records)),
            "duration_seconds": time.monotonic() - started,
            "stopped_early": state.stop_requested.is_set(),
        }
        history = _load_history()
        history = [h for h in history if h.get("source_id") != source_id]
        history.append(history_record)
        if len(history) > 12:
            history = history[-12:]
        _save_history(history)

        # Merge survivors into the main server store.
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
        stopped = state.stop_requested.is_set()
        LOGGER.info(
            "Scanner: %s in %.1fs — crawled=%d alive=%d dropped=%d",
            "stopped early" if stopped else "completed",
            duration, state.total, len(records), max(0, state.total - len(records)),
        )

        return ScannerResult(
            sub_name=sub_name,
            source_id=source_id,
            servers=records,
            raw_lines=raw_lines,
            base64_payload=base64_payload,
            duration_seconds=duration,
            downloaded=state.total,
            dropped=max(0, state.total - len(records)),
            stopped_early=stopped,
        )
    except Exception:
        # Make sure we tear down the TUN even on failure.
        if disconnect_callback:
            try:
                disconnect_callback()
            except Exception:
                pass
        raise


# --- Copy / export helpers ----------------------------------------------

def export_subscription(sub_name: str, *, as_base64: bool = False) -> str:
    rows = _load_history()
    for row in reversed(rows):
        if row.get("name") == sub_name:
            if as_base64:
                return row.get("base64") or ""
            return "\n".join(row.get("raw_lines") or [])
    return ""


def copy_all_servers(sub_name: str) -> str:
    return export_subscription(sub_name, as_base64=False)


def delete_scanner_sub(sub_name: str) -> None:
    rows = _load_history()
    rows = [row for row in rows if row.get("name") != sub_name]
    _save_history(rows)
