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
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .constants import DATA_DIR, MAX_DISCOVERY_CONFIGS
from .crawler import crawl_telegram_channels, load_channels, load_channel_specs
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
from .resource_tuning import current_resource_profile
from .storage import JsonStore

LOGGER = get_logger("scanner")

# --- Adaptive scanner profile -------------------------------------------
RESOURCE_PROFILE = current_resource_profile()
SCAN_CRAWL_WORKERS = RESOURCE_PROFILE.crawl_workers
SCAN_CRAWL_TIMEOUT_S = 12.0
SCAN_PROBE_WORKERS = min(12, RESOURCE_PROFILE.probe_workers)
SCAN_PROBE_TIMEOUT_S = 3.5
SCAN_PROBE_RETRY_LIMIT = 1
SCAN_PROBE_RETRY_WORKERS = RESOURCE_PROFILE.retry_workers
SCAN_PROBE_QUEUE_LIMIT = min(
    24,
    max(SCAN_PROBE_WORKERS, RESOURCE_PROFILE.internal_queue_limit),
)
SCAN_MAX_SERVERS = 240
SCAN_TARGET_HEALTHY = 5

DEFAULT_RANK1_PER_CHANNEL = 3
DEFAULT_RANK2_PER_CHANNEL = 3
# RANK1_CHANNELS is now represented by rank=1 entries in channels.json.
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
SCANNER_EXPORT_DIR = DATA_DIR / "scanner_subscriptions"


def normalize_rank_limit(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 3
    return parsed if 1 <= parsed <= 20 else 3


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
    """Generate the sub name.

    v1.7.0-rc.3: always use "sub" as the name.  Each scan updates the
    same "sub" source — no need for the user to pick a name.
    """
    cleaned = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", " ", (custom or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:64].strip()
    return cleaned or f"Scanner {datetime.now().strftime('%Y-%m-%d %H-%M')}"


def _probe_one(
    raw_config: str,
    *,
    timeout: float = SCAN_PROBE_TIMEOUT_S,
    stop_event: threading.Event | None = None,
) -> int | None:
    from .xray import probe_outbound_delay
    if stop_event is not None and stop_event.is_set():
        return None
    try:
        delay = probe_outbound_delay(raw_config, timeout=timeout, cancel_event=stop_event)
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


def _crawl_only(
    *,
    language: str = "fa",
    rank1_limit: int = DEFAULT_RANK1_PER_CHANNEL,
    rank2_limit: int = DEFAULT_RANK2_PER_CHANNEL,
    stage: StageCallback | None = None,
    crawl_progress: ProgressCallback | None = None,
    eta_callback: ETACallback | None = None,
    log_callback: LogCallback | None = None,
    state: _ProbeState,
) -> list[str]:
    """Crawl Telegram channels and return raw config URIs.

    v1.7.0-rc.3: separated from probing so that the VPN can be
    disconnected between crawl and probe (exactly as DicodeConfigChecker
    does in its two-stage flow).
    """
    def _log(line: str) -> None:
        state.log_lines.append(line)
        if log_callback:
            log_callback(line)
        LOGGER.info("scanner: %s", line)

    if stage:
        stage(tr(language, "scanner_stage2_crawl"))
    _log(tr(language, "scanner_stage2_crawl"))

    specs = load_channel_specs()
    if not specs:
        raise RuntimeError(
            tr(language, "scanner_no_channels")
            if language != "en"
            else "Telegram channel list is missing."
        )
    rank1_limit = normalize_rank_limit(rank1_limit)
    rank2_limit = normalize_rank_limit(rank2_limit)
    channels = [item.name for item in specs]
    _log(f"Channels: {len(channels)} (rank1={rank1_limit}/ch, rank2={rank2_limit}/ch)")

    rank1 = [item.name for item in specs if item.rank == 1]
    rank2 = [item.name for item in specs if item.rank == 2]
    _log(f"Rank-1: {len(rank1)}, Rank-2: {len(rank2)}")

    crawl_eta = ETAEstimator()
    crawl_done_count = 0
    total_channels = len(channels)

    def _crawl_group(group: list[str], limit: int, label: str) -> list[str]:
        nonlocal crawl_done_count
        if not group:
            return []
        _log(f"Crawling {len(group)} {label} channels...")
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
            stop_event=state.stop_requested,
            retry_limit=1,
        )
        crawl_done_count += len(group)
        return result

    raw_configs = _crawl_group(rank1, rank1_limit, "rank-1") + _crawl_group(rank2, rank2_limit, "rank-2")
    crawl_progress and crawl_progress(total_channels, total_channels)
    eta_callback and eta_callback(format_seconds(0))
    _log(f"Crawl done: {len(raw_configs)} raw configs")

    if state.stop_requested.is_set():
        _log("Stop requested after crawl.")
        return []
    if not raw_configs:
        raise RuntimeError(
            tr(language, "scanner_no_configs")
            if language != "en"
            else "No configs collected from Telegram."
        )

    unique: list[str] = []
    seen: set[str] = set()
    for raw in raw_configs:
        key = normalize_key(raw)
        if key in seen:
            continue
        seen.add(key)
        unique.append(raw)
        if len(unique) >= MAX_DISCOVERY_CONFIGS:
            break
    _log(f"After dedup: {len(unique)} unique configs")
    return unique


def _probe_only(
    *,
    language: str = "fa",
    configs: list[str],
    stage: StageCallback | None = None,
    probe_progress: ProgressCallback | None = None,
    eta_callback: ETACallback | None = None,
    alive_count_callback: AliveCountCallback | None = None,
    log_callback: LogCallback | None = None,
    state: _ProbeState,
) -> list[str]:
    """Probe a list of config URIs and return the alive ones.

    v1.7.0-rc.3: separated from crawling so that the VPN can be
    disconnected before probing.
    """
    def _log(line: str) -> None:
        state.log_lines.append(line)
        if log_callback:
            log_callback(line)
        LOGGER.info("scanner: %s", line)

    if not configs:
        return []

    if stage:
        stage(tr(language, "scanner_stage2_probe"))
    _log(tr(language, "scanner_stage2_probe"))
    _log(f"Testing {len(configs)} configs with {SCAN_PROBE_WORKERS} parallel workers...")

    state.total = len(configs)
    state.completed = 0
    if probe_progress:
        probe_progress(0, state.total)

    probe_eta = ETAEstimator()
    probe_eta.update(0, state.total)

    # Submit a bounded window instead of allocating one Future (and one Xray
    # process shortly afterwards) for every discovered config.
    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=SCAN_PROBE_WORKERS,
        thread_name_prefix="dicodePing-probe",
    )
    config_iter = iter(configs)
    future_to_raw: dict[concurrent.futures.Future[int | None], str] = {}

    def _fill_queue() -> None:
        while len(future_to_raw) < SCAN_PROBE_QUEUE_LIMIT:
            try:
                raw = next(config_iter)
            except StopIteration:
                return
            future = pool.submit(
                _probe_one,
                raw,
                timeout=SCAN_PROBE_TIMEOUT_S,
                stop_event=state.stop_requested,
            )
            future_to_raw[future] = raw

    _fill_queue()
    cancelled = False
    try:
        while future_to_raw:
            if state.stop_requested.is_set():
                cancelled = True
                for pending in future_to_raw:
                    pending.cancel()
                _log("Stop requested; cancelling active probes.")
                break
            completed, _ = concurrent.futures.wait(
                tuple(future_to_raw),
                timeout=0.15,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not completed:
                continue
            for future in completed:
                raw = future_to_raw.pop(future)
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
                host = ""
                try:
                    ep = parse_endpoint(raw)
                    if ep:
                        host = f"{ep.host}:{ep.port}"
                except Exception:
                    pass
                if ping_ms is not None:
                    _log(f"[{done}/{state.total}] ✓ {host} → {ping_ms}ms (alive={alive_count})")
                else:
                    _log(f"[{done}/{state.total}] ✗ {host}")
            if len(state.alive) >= SCAN_TARGET_HEALTHY:
                cancelled = True
                for pending in future_to_raw:
                    pending.cancel()
                _log(
                    f"Healthy target reached ({SCAN_TARGET_HEALTHY}); "
                    "stopping new probe submissions."
                )
                break
            _fill_queue()
    finally:
        # Even an early stop joins the bounded active set. Each probe observes
        # the stop event and owns a short timeout, so no executor thread or
        # Xray child can outlive the ScannerSession.
        pool.shutdown(wait=True, cancel_futures=cancelled)

    _log(f"Test done: {len(state.alive)} alive out of {state.total}")

    if not state.stop_requested.is_set() and SCAN_PROBE_RETRY_LIMIT > 0:
        with state.lock:
            alive_keys = {a[0] for a in state.alive}
            retried = [raw for raw in configs if raw not in alive_keys][:SCAN_PROBE_RETRY_LIMIT]
        if retried:
            _log(f"Retrying {len(retried)} failed configs...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_PROBE_RETRY_WORKERS) as pool:
                future_to_raw = {
                    pool.submit(
                        _probe_one,
                        raw,
                        timeout=SCAN_PROBE_TIMEOUT_S,
                        stop_event=state.stop_requested,
                    ): raw
                    for raw in retried
                }
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
                        _log(f"Retry ✓ → {ping_ms}ms")

    with state.lock:
        state.alive.sort(key=lambda item: item[1])
        state.alive = state.alive[: min(SCAN_MAX_SERVERS, SCAN_TARGET_HEALTHY)]
        _log(f"Final alive: {len(state.alive)}")
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
    validate_connection_callback: Callable[[], bool] | None = None,
    bootstrap_server_id: str | None = None,
) -> ScannerResult:
    """Execute the staged scan and persist the result."""
    started = time.monotonic()
    # Reuse the caller's Event directly.  The old watcher thread waited
    # forever after every successful scan and leaked one thread per run.
    state = _ProbeState(stop_requested=stop_event or threading.Event())
    rank1_limit = normalize_rank_limit(rank1_limit)
    rank2_limit = normalize_rank_limit(rank2_limit)

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
                        raise RuntimeError("Scanner stopped while connecting; no results were saved.")
                    if is_connected_callback and is_connected_callback():
                        _log("Bootstrap TUN is up.")
                        break
                    time.sleep(0.5)
                else:
                    raise RuntimeError("Bootstrap TUN did not reach the connected state in 20 seconds.")
                if validate_connection_callback and not validate_connection_callback():
                    raise RuntimeError("Bootstrap TUN failed real HTTP validation.")
        except Exception:
            _log(f"Stage 1 failed: {__import__('traceback').format_exc()}")
            raise
    else:
        _log(tr(language, "scanner_stage1_skip"))
        if connect_callback:
            connect_callback(bootstrap_server_id)
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                if state.stop_requested.is_set():
                    raise RuntimeError("Scanner stopped while connecting; no results were saved.")
                if is_connected_callback and is_connected_callback():
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Existing bootstrap TUN is not connected.")
            if validate_connection_callback and not validate_connection_callback():
                raise RuntimeError("Existing bootstrap TUN failed real HTTP validation.")

    try:
        # --- Stage 2a: Crawl (through the bootstrap VPN) ---------------
        if stage_change:
            stage_change(2, tr(language, "scanner_stage2"))
        configs = _crawl_only(
            language=language,
            rank1_limit=rank1_limit,
            rank2_limit=rank2_limit,
            stage=stage,
            crawl_progress=crawl_progress,
            eta_callback=eta_callback,
            log_callback=_log,
            state=state,
        )

        if state.stop_requested.is_set():
            _log("Stop requested after crawl; saving what we have (none).")
            raise RuntimeError(tr(language, "scanner_no_alive_stopped"))

        # --- Stage 2b: Disconnect the bootstrap VPN -------------------
        # v1.7.0-rc.3: disconnect the VPN BEFORE probing, exactly as
        # DicodeConfigChecker does.  Probing through the VPN would test
        # the bootstrap server, not the crawled configs.
        if disconnect_callback:
            _log("Disconnecting VPN before testing configs...")
            disconnect_callback()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if not is_connected_callback or not is_connected_callback():
                    _log("VPN disconnected and bootstrap process stopped.")
                    break
                time.sleep(0.2)
            else:
                _log("Bootstrap disconnect timed out; running one bounded force-cleanup.")
                disconnect_callback()
                time.sleep(1.0)
                if is_connected_callback and is_connected_callback():
                    raise RuntimeError(
                        "contaminationRisk: bootstrap TUN/process is still active; probes were not started."
                    )

        # --- Stage 2c: Probe (without VPN) ----------------------------
        alive_raws = _probe_only(
            language=language,
            configs=configs,
            stage=stage,
            probe_progress=probe_progress,
            eta_callback=eta_callback,
            alive_count_callback=alive_count_callback,
            log_callback=_log,
            state=state,
        )

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
        from .config_profile import classify_config_profile
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
                    profile_tag=classify_config_profile(raw, endpoint.host),
                )
            )

        raw_lines = [set_display_name(raw, "") for raw, _ in alive]
        base64_payload = b64_encode_text("\n".join(raw_lines))

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
        current = store.load_servers()
        by_id = {s.id: s for s in current if s.source_id != source_id}
        for record in records:
            by_id[record.id] = record
        merged = list(by_id.values())
        SCANNER_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        store.save_scanner_transaction(
            settings=settings,
            servers=merged,
            history_path=SCANNER_HISTORY_FILE,
            history=history,
            raw_path=SCANNER_EXPORT_DIR / f"{source_id}.txt",
            raw_payload="\n".join(raw_lines),
            base64_path=SCANNER_EXPORT_DIR / f"{source_id}.base64.txt",
            base64_payload=base64_payload,
        )

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
    def _best_verified() -> ServerRecord | None:
        from .protocols import blob_to_config

        candidates = [
            item
            for item in service.auto_candidates(store.load_servers())
            if item.source_id == "default"
        ][:5]
        if not candidates:
            return None
        verified: list[tuple[int, ServerRecord]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(candidates))) as pool:
            futures = {
                pool.submit(_probe_one, blob_to_config(item.config_blob), timeout=5.0): item
                for item in candidates
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    ping = future.result()
                except Exception:
                    ping = None
                if ping is not None:
                    verified.append((ping, futures[future]))
        if not verified:
            return None
        verified.sort(key=lambda row: row[0])
        verified[0][1].ping_ms = verified[0][0]
        return verified[0][1]

    best = _best_verified()
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
            best = _best_verified()
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
