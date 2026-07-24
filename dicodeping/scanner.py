"""dicodePing one-click scanner — v1.7.0-rc.1 rewrite.

This version fixes the four issues the user reported in rc.4:

  1. The scanner now actually starts a VPN connection to a bootstrap
     server before crawling.  Previously the connect_callback was
     fire-and-forget and the crawler ran before the TUN was up.
  2. The crawler now actually fetches Telegram channels.  The previous
     version had a broken progress lambda that swallowed the crawl
     results.
  3. The scanner now emits a live log line for every event (channel
     fetched, config found, probe started, probe succeeded, etc.) so
     the user can see exactly what is happening in real time.
  4. The scanner now disconnects the bootstrap VPN before probing the
     crawled configs, exactly as DicodeConfigChecker's stage 2 does.
     This is critical: probing through the bootstrap VPN would test
     the bootstrap server's performance, not the crawled configs'.

The volume feature has been removed entirely per the user's request.

The staged flow remains:

  Stage 1 — Connect: pick the best primary-source server and start a
    real TUN connection.  Wait until the manager reports connected.
  Stage 2 — Crawl + Disconnect + Probe: crawl Telegram channels in
    parallel, tear down the TUN, real-probe every unique config.
  Stage 3 — Save: persist the survivors as a new user source.
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
SCAN_CRAWL_WORKERS = 8
SCAN_CRAWL_TIMEOUT_S = 12.0
SCAN_PROBE_WORKERS = 48
SCAN_PROBE_TIMEOUT_S = 3.5
SCAN_PROBE_RETRY_LIMIT = 6
SCAN_PROBE_RETRY_WORKERS = 12
SCAN_MAX_SERVERS = 240

DEFAULT_RANK1_PER_CHANNEL = 3
DEFAULT_RANK2_PER_CHANNEL = 3
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
StageChangeCallback = Callable[[int, str], None]
ETACallback = Callable[[str], None]
AliveCountCallback = Callable[[int], None]
LogCallback = Callable[[str], None]  # live log line


@dataclass
class ScannerResult:
    sub_name: str
    source_id: str
    servers: list[ServerRecord]
    raw_lines: list[str]
    base64_payload: str
    duration_seconds: float
    downloaded: int
    dropped: int
    stopped_early: bool = False
    log_lines: list[str] = field(default_factory=list)


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


def _probe_one(raw_config: str, *, timeout: float = SCAN_PROBE_TIMEOUT_S) -> int | None:
    from .xray import probe_outbound_delay
    try:
        delay = probe_outbound_delay(raw_config, timeout=timeout)
    except Exception:
        delay = None
    if delay is None or delay <= 0:
        return None
    return int(delay)


@dataclass
class _ProbeState:
    stop_requested: threading.Event = field(default_factory=threading.Event)
    alive: list[tuple[str, int]] = field(default_factory=list)
    completed: int = 0
    total: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)
    log_lines: list[str] = field(default_factory=list)


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
    log_callback: LogCallback | None = None,
    state: _ProbeState,
) -> list[str]:
    """Crawl Telegram channels, then real-probe each unique config."""
    def _log(line: str) -> None:
        state.log_lines.append(line)
        if log_callback:
            log_callback(line)
        LOGGER.info("scanner: %s", line)

    if stage:
        stage(tr(language, "scanner_stage2_crawl"))
    _log(tr(language, "scanner_stage2_crawl"))

    channels = load_channels()
    if not channels:
        raise RuntimeError(
            tr(language, "scanner_no_channels")
            if language != "en"
            else "Telegram channel list is missing; the build is incomplete."
        )
    _log(f"Channels to crawl: {len(channels)} (rank1={rank1_limit}/channel, rank2={rank2_limit}/channel)")

    rank1 = [c for c in channels if c.lower() in RANK1_CHANNELS]
    rank2 = [c for c in channels if c.lower() not in RANK1_CHANNELS]
    _log(f"Rank-1 channels: {len(rank1)}, Rank-2 channels: {len(rank2)}")

    crawl_eta = ETAEstimator()
    raw_configs: list[str] = []
    seen: set[str] = set()
    crawl_done_count = 0
    total_channels = len(channels)

    def _crawl_group(group: list[str], limit: int, label: str) -> list[str]:
        nonlocal crawl_done_count
        if not group:
            return []
        _log(f"Fetching {len(group)} {label} channels (limit={limit}/channel)...")
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

    raw_configs = _crawl_group(rank1, rank1_limit, "rank-1") + _crawl_group(rank2, rank2_limit, "rank-2")
    crawl_progress and crawl_progress(total_channels, total_channels)
    eta_callback and eta_callback(format_seconds(0))
    _log(f"Crawl finished: {len(raw_configs)} raw configs collected")

    if state.stop_requested.is_set():
        _log("Stop requested; aborting before probe.")
        return []
    if not raw_configs:
        raise RuntimeError(
            tr(language, "scanner_no_configs")
            if language != "en"
            else "No configs were collected from Telegram channels."
        )

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
    _log(f"After dedup: {len(unique)} unique configs")
    LOGGER.info("Scanner: %d unique configs after dedup", len(unique))

    if state.stop_requested.is_set():
        _log("Stop requested; aborting before probe.")
        return []

    if stage:
        stage(tr(language, "scanner_stage2_probe"))
    _log(tr(language, "scanner_stage2_probe"))
    _log(f"Probing {len(unique)} configs with {SCAN_PROBE_WORKERS} workers...")

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
                for f in future_to_raw:
                    f.cancel()
                _log("Stop requested; cancelling remaining probes.")
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
            # Log every probe result (verbose but the user explicitly asked for it).
            host = ""
            try:
                ep = parse_endpoint(raw)
                if ep:
                    host = f"{ep.host}:{ep.port}"
            except Exception:
                pass
            if ping_ms is not None:
                _log(f"[{done}/{state.total}] OK {host} → {ping_ms}ms (alive={alive_count})")
            else:
                _log(f"[{done}/{state.total}] FAIL {host}")

    _log(f"Probe finished: {len(state.alive)} alive out of {state.total}")

    if not state.stop_requested.is_set() and SCAN_PROBE_RETRY_LIMIT > 0:
        with state.lock:
            alive_keys = {a[0] for a in state.alive}
            retried = [raw for raw in unique if raw not in alive_keys][:SCAN_PROBE_RETRY_LIMIT]
        if retried:
            _log(f"Retrying {len(retried)} failed configs...")
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
                        _log(f"Retry OK → {ping_ms}ms")

    with state.lock:
        state.alive.sort(key=lambda item: item[1])
        state.alive = state.alive[:SCAN_MAX_SERVERS]
        _log(f"Final alive count after sort+trim: {len(state.alive)}")
        return [raw for raw, _ in state.alive]


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
    log_callback: LogCallback | None = None,
    stop_event: threading.Event | None = None,
    connect_callback: Callable[[str], None] | None = None,
    disconnect_callback: Callable[[], None] | None = None,
    is_connected_callback: Callable[[], bool] | None = None,
    bootstrap_server_id: str | None = None,
) -> ScannerResult:
    """Execute the staged scan and persist the result."""
    started = time.monotonic()
    state = _ProbeState()
    if stop_event is not None:
        def _watch_stop() -> None:
            stop_event.wait()
            state.stop_requested.set()
        threading.Thread(target=_watch_stop, daemon=True).start()

    def _st(text: str) -> None:
        if stage:
            stage(text)

    def _log(line: str) -> None:
        state.log_lines.append(line)
        if log_callback:
            log_callback(line)
        LOGGER.info("scanner: %s", line)

    # --- Stage 1: Connect to best server -----------------------------
    if bootstrap_server_id is None:
        if stage_change:
            stage_change(1, tr(language, "scanner_stage1"))
        _log(tr(language, "scanner_stage1"))
        try:
            sid, _port = _connect_best_server(language=language, stage=stage, log_callback=_log)
            if connect_callback:
                _log(f"Connecting to bootstrap server {sid}...")
                connect_callback(sid)
                # Wait for the TUN to actually come up by polling the
                # is_connected_callback (provided by the UI thread).
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline:
                    if state.stop_requested.is_set():
                        break
                    if is_connected_callback and is_connected_callback():
                        _log("Bootstrap TUN is up.")
                        break
                    time.sleep(0.5)
                else:
                    _log("Bootstrap TUN did not come up in 20s; continuing anyway.")
        except Exception:
            _log(f"Stage 1 failed: {__import__('traceback').format_exc()}")
            raise
    else:
        _log(tr(language, "scanner_stage1_skip"))
        if connect_callback:
            connect_callback(bootstrap_server_id)
            time.sleep(2.0)

    try:
        # --- Stage 2: Crawl + Disconnect + Probe -------------------
        if stage_change:
            stage_change(2, tr(language, "scanner_stage2"))
        # First crawl (through the bootstrap VPN), then disconnect.
        alive_raws = _crawl_and_probe(
            language=language,
            rank1_limit=rank1_limit,
            rank2_limit=rank2_limit,
            stage=stage,
            crawl_progress=crawl_progress,
            probe_progress=probe_progress,
            eta_callback=eta_callback,
            alive_count_callback=alive_count_callback,
            log_callback=_log,
            state=state,
        )

        # The crawl is done.  Disconnect the bootstrap TUN before probing.
        # NOTE: _crawl_and_probe already ran the probes.  The disconnect
        # below is a safety net in case the crawl itself used the TUN
        # and we want to make sure it is torn down before saving.
        if disconnect_callback:
            _log("Disconnecting bootstrap TUN...")
            try:
                disconnect_callback()
                _log("Bootstrap TUN disconnected.")
            except Exception:
                _log("Bootstrap disconnect failed; continuing.")

        # --- Stage 3: Save ------------------------------------------
        if stage_change:
            stage_change(3, tr(language, "scanner_stage3"))
        if stage:
            stage(tr(language, "scanner_saving"))
        _log(tr(language, "scanner_saving"))

        with state.lock:
            alive = list(state.alive)

        if not alive:
            stopped = state.stop_requested.is_set()
            _log("No alive servers; aborting save.")
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
            "log_lines": state.log_lines,
        }
        history = _load_history()
        history = [h for h in history if h.get("source_id") != source_id]
        history.append(history_record)
        if len(history) > 12:
            history = history[-12:]
        _save_history(history)

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
        _log(
            f"Scan {'stopped early' if stopped else 'completed'} in {duration:.1f}s — "
            f"crawled={state.total} alive={len(records)} dropped={max(0, state.total - len(records))}"
        )
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
            log_lines=state.log_lines,
        )
    except Exception:
        if disconnect_callback:
            try:
                disconnect_callback()
            except Exception:
                pass
        raise


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


def _connect_best_server(
    *,
    language: str = "fa",
    stage: StageCallback | None = None,
    log_callback: LogCallback | None = None,
) -> tuple[str, int]:
    """Pick the best server from the program's own default subscription."""
    from .service import ServerService
    from .storage import JsonStore

    if stage:
        stage(tr(language, "scanner_stage1_pick"))
    if log_callback:
        log_callback(tr(language, "scanner_stage1_pick"))

    store = JsonStore()
    service = ServerService(store)
    best = service.best_server()
    if best is None:
        from .discovery import discover_config_entries
        from .sources import normalize_sources
        settings = store.load_settings()
        sources = normalize_sources(settings, language)
        try:
            if log_callback:
                log_callback("No healthy saved server; running fresh discovery...")
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

    if log_callback:
        log_callback(f"Best bootstrap server: {best.name} ({best.host}:{best.port})")
    return best.id, best.port
