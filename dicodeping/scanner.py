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
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .constants import DATA_DIR, MAX_DISCOVERY_CONFIGS
from .config_checker import ConfigQualityResult, test_config
from .crawler import crawl_telegram_channels, load_channels, load_channel_specs, verify_telegram_route
from .diagnostics import get_logger
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
from .resource_tuning import current_resource_profile, resource_mode_from_settings
from .security_rating import assess_config_security
from .geo import GeoResolver
from .net import resolve_ipv4
from .storage import JsonStore

LOGGER = get_logger("scanner")

# --- Adaptive scanner profile -------------------------------------------
RESOURCE_PROFILE = current_resource_profile()
SCAN_CRAWL_WORKERS = min(18, max(8, RESOURCE_PROFILE.crawl_workers + 2))
SCAN_CRAWL_TIMEOUT_S = 5.0
SCAN_PROBE_WORKERS = min(16, max(6, RESOURCE_PROFILE.probe_workers))
SCAN_PROBE_TIMEOUT_S = 2.6
SCAN_PROBE_ATTEMPTS = 1
SCAN_PROBE_MIN_SUCCESS = 1
SCAN_PROBE_RETRY_LIMIT = 0
SCAN_PROBE_RETRY_WORKERS = min(8, max(3, RESOURCE_PROFILE.retry_workers))
SCAN_PROBE_QUEUE_LIMIT = min(
    24,
    max(SCAN_PROBE_WORKERS, RESOURCE_PROFILE.internal_queue_limit),
)
SCAN_MAX_SERVERS = 80
SCAN_MAX_PROBE_CONFIGS = 120
SCAN_CRAWL_TARGET_RAW = 180
SCAN_CRAWL_MIN_CHANNELS = 36
SCAN_BOOTSTRAP_CONNECT_TIMEOUT_S = 55.0
SCAN_BOOTSTRAP_DISCONNECT_TIMEOUT_S = 18.0
SCANNER_SOURCE_ID = "scanner-sub"
SCANNER_SOURCE_NAME = "SUB"

DEFAULT_RANK1_PER_CHANNEL = 8
DEFAULT_RANK2_PER_CHANNEL = 9
# RANK1_CHANNELS is now represented by rank=1 entries in channels.json.
# -------------------------------------------------------------------------

StageCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]
StageChangeCallback = Callable[[int, str], None]
ETACallback = Callable[[str], None]  # retained for API compatibility; RC3 no longer shows ETA
AliveCountCallback = Callable[[int], None]
LogCallback = Callable[[str], None]
MetricsCallback = Callable[[dict[str, object]], None]
ConnectionWaitCallback = Callable[[float], tuple[bool, str]]


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
SCANNER_STAGE1_RAW_FILE = SCANNER_EXPORT_DIR / "scanner-stage1-raw.txt"
SCANNER_STAGE1_META_FILE = SCANNER_EXPORT_DIR / "scanner-stage1-meta.json"


def normalize_rank_limit(value: object, default: int = DEFAULT_RANK1_PER_CHANNEL) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if 1 <= parsed <= 20 else default


def _save_stage1_snapshot(
    configs: list[str],
    *,
    channel_count: int,
    rank1_limit: int,
    rank2_limit: int,
) -> None:
    """Persist the collected candidates before the bootstrap VPN is stopped.

    This makes the two-stage boundary explicit and recoverable: Telegram data is
    first committed to disk, then the app disconnects its own VPN, and only then
    are the saved candidates probed from the user's real network.
    """
    SCANNER_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    raw_payload = "\n".join(configs) + ("\n" if configs else "")
    raw_tmp = SCANNER_STAGE1_RAW_FILE.with_suffix(".tmp")
    meta_tmp = SCANNER_STAGE1_META_FILE.with_suffix(".tmp")
    raw_tmp.write_text(raw_payload, encoding="utf-8")
    meta_tmp.write_text(
        json.dumps(
            {
                "generated_at": utc_now(),
                "channel_count": channel_count,
                "rank1_limit": rank1_limit,
                "rank2_limit": rank2_limit,
                "candidate_count": len(configs),
                "raw_file": SCANNER_STAGE1_RAW_FILE.name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    raw_tmp.replace(SCANNER_STAGE1_RAW_FILE)
    meta_tmp.replace(SCANNER_STAGE1_META_FILE)


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
    """Return the single stable scanner subscription name.

    RC5 intentionally ignores custom names: every run atomically replaces the
    same local source and export, so the UI never accumulates duplicate subs.
    """
    del custom
    return SCANNER_SOURCE_NAME


def _probe_one(
    raw_config: str,
    *,
    timeout: float = SCAN_PROBE_TIMEOUT_S,
    stop_event: threading.Event | None = None,
) -> ConfigQualityResult:
    return test_config(
        raw_config,
        attempts=SCAN_PROBE_ATTEMPTS,
        min_success=SCAN_PROBE_MIN_SUCCESS,
        per_attempt_timeout=timeout,
        stop_event=stop_event,
    )


@dataclass
class _ProbeState:
    stop_requested: threading.Event = field(default_factory=threading.Event)
    alive: list[tuple[str, ConfigQualityResult]] = field(default_factory=list)
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
    metrics_callback: MetricsCallback | None = None,
    log_callback: LogCallback | None = None,
    socks_port: int = 0,
    state: _ProbeState,
) -> list[str]:
    """Crawl all Telegram channels in one bounded parallel pass."""
    del eta_callback  # RC3 intentionally removed finish-time estimates.

    def _log(line: str) -> None:
        # The top-level run_scan logger owns history and diagnostics. Avoid
        # duplicate UI rows, duplicate file writes, and unnecessary disk I/O.
        if log_callback:
            log_callback(line)
        else:
            state.log_lines.append(line)
            LOGGER.info("scanner: %s", line)

    if stage:
        stage(tr(language, "scanner_stage2_crawl"))
    _log("[STAGE] " + tr(language, "scanner_stage2_crawl"))

    specs = load_channel_specs()
    if not specs:
        raise RuntimeError(
            tr(language, "scanner_no_channels")
            if language != "en"
            else "Telegram channel list is missing."
        )
    rank1_limit = normalize_rank_limit(rank1_limit, DEFAULT_RANK1_PER_CHANNEL)
    rank2_limit = normalize_rank_limit(rank2_limit, DEFAULT_RANK2_PER_CHANNEL)
    specs = sorted(specs, key=lambda item: (item.rank, item.name.casefold()))
    channels = [item.name for item in specs]
    limits = {item.name: (rank1_limit if item.rank == 1 else rank2_limit) for item in specs}
    rank1_count = sum(1 for item in specs if item.rank == 1)
    rank2_count = len(specs) - rank1_count
    route = (f"SOCKS5 127.0.0.1:{socks_port} -> t.me/TUN fallback" if socks_port else "t.me/TUN")
    _log(
        f"[TG][INFO] channels={len(channels)} rank1={rank1_count} rank2={rank2_count} "
        f"workers={SCAN_CRAWL_WORKERS} route={route}"
    )

    started = time.monotonic()
    transferred = 0
    collected = 0
    metric_lock = threading.Lock()

    def _channel_result(result, done: int, total: int) -> None:
        nonlocal transferred, collected
        with metric_lock:
            transferred += max(0, int(getattr(result, "bytes_received", 0)))
            collected += max(0, int(getattr(result, "picked", 0)))
            elapsed = max(0.001, time.monotonic() - started)
            channels_per_second = done / elapsed
            bytes_per_second = transferred / elapsed
        if result.ok:
            local_rate = int(result.bytes_received / max(0.001, result.elapsed_ms / 1000))
            _log(
                f"[TG][OK] {done}/{total} @{result.channel} | "
                f"configs={result.picked}/{result.found} | "
                f"{result.bytes_received / 1024:.1f} KiB | "
                f"{result.elapsed_ms} ms | {local_rate / 1024:.1f} KiB/s"
            )
        else:
            compact_error = str(result.error).replace("\n", " ")[-320:]
            _log(f"[TG][ERR] {done}/{total} @{result.channel} | {compact_error}")
        if metrics_callback:
            metrics_callback(
                {
                    "phase": "crawl",
                    "current": done,
                    "total": total,
                    "channels_per_second": channels_per_second,
                    "bytes_per_second": bytes_per_second,
                    "configs": collected,
                    "bytes": transferred,
                }
            )

    # Validate the same route the workers will use before creating hundreds of
    # requests.  The successful preflight result is reused instead of fetched
    # twice.  Rank-1 channels are first because they are the curated source set.
    preflight = verify_telegram_route(
        channels,
        per_channel_limits=limits,
        timeout=SCAN_CRAWL_TIMEOUT_S,
        socks_port=socks_port,
        stop_event=state.stop_requested,
        attempts=min(3, max(1, rank1_count)),
    )
    if not preflight.ok:
        raise RuntimeError(
            "Telegram preview is not reachable through the verified bootstrap VPN: "
            + str(preflight.error or "route validation failed")
        )
    _log(
        f"[TG][PREFLIGHT][OK] @{preflight.channel} via {preflight.transport} | "
        f"configs={preflight.picked}/{preflight.found} | {preflight.elapsed_ms} ms"
    )
    _channel_result(preflight, 1, len(channels))
    remaining_channels = [item for item in channels if item != preflight.channel]

    crawled = crawl_telegram_channels(
        channels=remaining_channels,
        per_channel_limits=limits,
        max_workers=SCAN_CRAWL_WORKERS,
        timeout=SCAN_CRAWL_TIMEOUT_S,
        progress=lambda done, _total, _ch: crawl_progress and crawl_progress(done + 1, len(channels)),
        result_callback=lambda result, done, _total: _channel_result(result, done + 1, len(channels)),
        stop_event=state.stop_requested,
        retry_limit=0,
        socks_port=socks_port,
        max_unique_configs=max(1, SCAN_CRAWL_TARGET_RAW - len(preflight.configs)),
        minimum_channels_before_target=max(0, min(SCAN_CRAWL_MIN_CHANNELS, len(channels)) - 1),
    )
    raw_configs = list(preflight.configs) + crawled
    if crawl_progress:
        crawl_progress(len(channels), len(channels))
    elapsed = max(0.001, time.monotonic() - started)
    _log(
        f"[TG][DONE] raw={len(raw_configs)} | transferred={transferred / 1024:.1f} KiB | "
        f"avg={transferred / elapsed / 1024:.1f} KiB/s | duration={elapsed:.2f}s"
    )

    if state.stop_requested.is_set():
        _log("[STOP] Stop requested after Telegram crawl.")
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
        if len(unique) >= min(MAX_DISCOVERY_CONFIGS, SCAN_MAX_PROBE_CONFIGS):
            break
    _log(f"[TG][DEDUP] unique={len(unique)} dropped={max(0, len(raw_configs) - len(unique))}")
    _save_stage1_snapshot(
        unique,
        channel_count=len(channels),
        rank1_limit=rank1_limit,
        rank2_limit=rank2_limit,
    )
    _log(f"[STORE][OK] stage1={SCANNER_STAGE1_RAW_FILE.name} candidates={len(unique)}")
    return unique


def _probe_only(
    *,
    language: str = "fa",
    configs: list[str],
    stage: StageCallback | None = None,
    probe_progress: ProgressCallback | None = None,
    eta_callback: ETACallback | None = None,
    alive_count_callback: AliveCountCallback | None = None,
    metrics_callback: MetricsCallback | None = None,
    log_callback: LogCallback | None = None,
    state: _ProbeState,
) -> list[str]:
    """Probe configs with a bounded Xray process window and live throughput."""
    del eta_callback  # RC3 shows real throughput instead of unreliable ETA.

    def _log(line: str) -> None:
        if log_callback:
            log_callback(line)
        else:
            state.log_lines.append(line)
            LOGGER.info("scanner: %s", line)

    if not configs:
        return []
    if stage:
        stage(tr(language, "scanner_stage2_probe"))
    _log("[STAGE] " + tr(language, "scanner_stage2_probe"))
    _log(
        f"[TEST][INFO] configs={len(configs)} workers={SCAN_PROBE_WORKERS} "
        f"attempts={SCAN_PROBE_ATTEMPTS} min_success={SCAN_PROBE_MIN_SUCCESS} "
        f"timeout={SCAN_PROBE_TIMEOUT_S:.1f}s engine=DicodeConfigChecker"
    )

    state.total = len(configs)
    state.completed = 0
    if probe_progress:
        probe_progress(0, state.total)

    started = time.monotonic()
    failed_raws: list[str] = []
    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=SCAN_PROBE_WORKERS,
        thread_name_prefix="dicodePing-probe",
    )
    config_iter = iter(configs)
    future_to_raw: dict[concurrent.futures.Future[ConfigQualityResult], str] = {}

    def _fill_queue() -> None:
        while len(future_to_raw) < SCAN_PROBE_QUEUE_LIMIT and not state.stop_requested.is_set():
            try:
                raw = next(config_iter)
            except StopIteration:
                return
            future_to_raw[pool.submit(
                _probe_one, raw, timeout=SCAN_PROBE_TIMEOUT_S, stop_event=state.stop_requested
            )] = raw

    _fill_queue()
    cancelled = False
    try:
        while future_to_raw:
            if state.stop_requested.is_set():
                cancelled = True
                for pending in future_to_raw:
                    pending.cancel()
                _log("[STOP] cancelling active connection tests")
                break
            ready, _ = concurrent.futures.wait(
                tuple(future_to_raw), timeout=0.10, return_when=concurrent.futures.FIRST_COMPLETED
            )
            if not ready:
                continue
            for future in ready:
                raw = future_to_raw.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = ConfigQualityResult(False, None, None, None, SCAN_PROBE_ATTEMPTS, 0, error=exc.__class__.__name__)
                with state.lock:
                    state.completed += 1
                    if result.ok and result.ping_ms is not None:
                        state.alive.append((raw, result))
                    else:
                        failed_raws.append(raw)
                    done = state.completed
                    alive_count = len(state.alive)
                if probe_progress:
                    probe_progress(done, state.total)
                if alive_count_callback:
                    alive_count_callback(alive_count)
                elapsed = max(0.001, time.monotonic() - started)
                tests_per_second = done / elapsed
                if metrics_callback:
                    metrics_callback(
                        {
                            "phase": "probe",
                            "current": done,
                            "total": state.total,
                            "tests_per_second": tests_per_second,
                            "alive": alive_count,
                        }
                    )
                endpoint = parse_endpoint(raw)
                host = f"{endpoint.host}:{endpoint.port}" if endpoint else "unknown"
                sample_text = ",".join(str(value) for value in result.samples_ms) or "-"
                if result.ok and result.ping_ms is not None:
                    _log(
                        f"[TEST][OK] {done}/{state.total} {host} | "
                        f"TCP={result.tcp_ms if result.tcp_ms is not None else '-'} ms "
                        f"XRAY={result.ping_ms} ms | samples=[{sample_text}] "
                        f"success={result.success_count}/{result.attempts} tester={result.tester} | "
                        f"alive={alive_count} speed={tests_per_second:.1f}/s"
                    )
                else:
                    _log(
                        f"[TEST][ERR] {done}/{state.total} {host} | "
                        f"TCP={result.tcp_ms if result.tcp_ms is not None else '-'} ms "
                        f"XRAY=- | success={result.success_count}/{result.attempts} tester={result.tester} "
                        f"error={result.error or 'failed'} samples=[{sample_text}] | "
                        f"speed={tests_per_second:.1f}/s"
                    )
            _fill_queue()
    finally:
        pool.shutdown(wait=True, cancel_futures=cancelled)

    # Only retry a small bounded sample when the first pass did not reach the
    # healthy target. Retrying every failure was a major source of RC2 stalls.
    if (
        not state.stop_requested.is_set()
        and failed_raws
        and SCAN_PROBE_RETRY_LIMIT > 0
    ):
        retry_rows = failed_raws[: min(12, len(failed_raws))]
        _log(f"[TEST][RETRY] count={len(retry_rows)}")
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(SCAN_PROBE_RETRY_WORKERS, len(retry_rows)),
            thread_name_prefix="dicodePing-retry",
        ) as retry_pool:
            retry_map = {
                retry_pool.submit(
                    _probe_one, raw, timeout=SCAN_PROBE_TIMEOUT_S + 0.8, stop_event=state.stop_requested
                ): raw
                for raw in retry_rows
            }
            for future in concurrent.futures.as_completed(retry_map):
                if state.stop_requested.is_set():
                    for pending in retry_map:
                        pending.cancel()
                    break
                try:
                    result = future.result()
                except Exception as exc:
                    result = ConfigQualityResult(False, None, None, None, SCAN_PROBE_ATTEMPTS, 0, error=exc.__class__.__name__)
                if result.ok and result.ping_ms is not None:
                    with state.lock:
                        state.alive.append((retry_map[future], result))
                    if alive_count_callback:
                        alive_count_callback(len(state.alive))
                    _log(f"[TEST][RETRY-OK] median={result.ping_ms} ms samples={list(result.samples_ms)}")

    with state.lock:
        state.alive.sort(key=lambda item: item[1].ping_ms or 999999)
        state.alive = state.alive[:SCAN_MAX_SERVERS]
        elapsed = max(0.001, time.monotonic() - started)
        _log(
            f"[TEST][DONE] checked={state.completed}/{state.total} alive={len(state.alive)} "
            f"avg={state.completed / elapsed:.1f}/s duration={elapsed:.2f}s"
        )
        return [raw for raw, _result in state.alive]


def _enrich_scanner_records(
    records: list[ServerRecord],
    *,
    store: JsonStore,
    log: LogCallback | None = None,
) -> None:
    """Resolve IP/location immediately and persist the enriched records.

    DNS is bounded to a short batch window and geolocation uses the shared
    cache, so saving a scanner SUB remains responsive while future launches can
    display flags without repeating the same network work.
    """
    if not records:
        return
    settings = store.load_settings()
    profile = current_resource_profile(resource_mode_from_settings(settings))
    workers = max(4, min(profile.dns_workers, len(records), 24))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures = {executor.submit(resolve_ipv4, record.host): record for record in records if record.host}
    done, pending = concurrent.futures.wait(futures, timeout=5.5)
    for future in done:
        record = futures[future]
        try:
            record.ip = future.result() or ""
        except Exception:
            record.ip = ""
    for future in pending:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)
    ips = [record.ip for record in records if record.ip]
    if log:
        log(f"[GEO][START] resolving locations for {len(ips)}/{len(records)} saved servers")
    geo_map = GeoResolver(store).resolve_many(ips, fast=True)
    located = 0
    for record in records:
        value = geo_map.get(record.ip, {})
        if not value:
            continue
        record.country = str(value.get("country") or "نامشخص")
        record.country_code = str(value.get("country_code") or "")
        record.region = str(value.get("region") or "")
        record.city = str(value.get("city") or "")
        record.isp = str(value.get("isp") or "")
        record.asn = str(value.get("asn") or "")
        record.geo_provider = str(value.get("geo_provider") or "")
        record.geo_confidence = str(value.get("geo_confidence") or "single")
        located += 1
    if log:
        log(f"[GEO][DONE] saved {located} server locations in the permanent scanner SUB")


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
    metrics_callback: MetricsCallback | None = None,
    log_callback: LogCallback | None = None,
    stop_event: threading.Event | None = None,
    connect_callback: Callable[[str], None] | None = None,
    disconnect_callback: Callable[[], None] | None = None,
    is_connected_callback: Callable[[], bool] | None = None,
    validate_connection_callback: Callable[[], bool] | None = None,
    proxy_port_callback: Callable[[], int] | None = None,
    wait_connected_callback: ConnectionWaitCallback | None = None,
    wait_disconnected_callback: ConnectionWaitCallback | None = None,
    bootstrap_server_id: str | None = None,
) -> ScannerResult:
    """Execute the staged scan and persist the result."""
    started = time.monotonic()
    # RC19 resource profile: optimized is always the default; professional is
    # an explicit setting and only raises bounded concurrency.
    selected_profile = current_resource_profile(resource_mode_from_settings(store.load_settings()))
    global SCAN_CRAWL_WORKERS, SCAN_PROBE_WORKERS, SCAN_PROBE_RETRY_WORKERS, SCAN_PROBE_QUEUE_LIMIT
    SCAN_CRAWL_WORKERS = min(24, max(6, selected_profile.crawl_workers + 2))
    SCAN_PROBE_WORKERS = min(28, max(6, selected_profile.probe_workers))
    SCAN_PROBE_RETRY_WORKERS = min(12, max(3, selected_profile.retry_workers))
    SCAN_PROBE_QUEUE_LIMIT = min(72, max(SCAN_PROBE_WORKERS, selected_profile.internal_queue_limit))
    # Reuse the caller's Event directly.  The old watcher thread waited
    # forever after every successful scan and leaked one thread per run.
    state = _ProbeState(stop_requested=stop_event or threading.Event())
    rank1_limit = normalize_rank_limit(rank1_limit, DEFAULT_RANK1_PER_CHANNEL)
    rank2_limit = normalize_rank_limit(rank2_limit, DEFAULT_RANK2_PER_CHANNEL)

    def _st(text: str) -> None:
        if stage:
            stage(text)

    def _log(line: str) -> None:
        state.log_lines.append(line)
        if len(state.log_lines) > 1200:
            del state.log_lines[: len(state.log_lines) - 1200]
        if log_callback:
            log_callback(line)
        LOGGER.info("scanner: %s", line)

    def _wait_connected(timeout: float) -> None:
        if wait_connected_callback is not None:
            ok, message = wait_connected_callback(timeout)
            if not ok:
                raise RuntimeError(message or "Bootstrap connection failed before the TUN became ready.")
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if state.stop_requested.is_set():
                raise RuntimeError("Scanner stopped while connecting; no results were saved.")
            if is_connected_callback and is_connected_callback():
                return
            time.sleep(0.25)
        raise RuntimeError(
            f"Bootstrap TUN did not reach the connected state in {int(timeout)} seconds. "
            "The connection worker did not report success."
        )

    def _wait_disconnected(timeout: float) -> None:
        if wait_disconnected_callback is not None:
            ok, message = wait_disconnected_callback(timeout)
            if not ok:
                raise RuntimeError(message or "Bootstrap disconnect did not finish safely.")
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not is_connected_callback or not is_connected_callback():
                return
            time.sleep(0.2)
        raise RuntimeError("contaminationRisk: Bootstrap TUN/process is still active; probes were not started.")

    # --- Stage 1: Connect to best server -----------------------------
    if bootstrap_server_id is None:
        if stage_change:
            stage_change(1, tr(language, "scanner_stage1"))
        _log("[CONNECT][START] starting dicodePing bootstrap VPN")
        _log(tr(language, "scanner_stage1"))
        try:
            sid, _port = _connect_best_server(language=language, stage=stage, log_callback=_log)
            if connect_callback:
                _log(f"Connecting to bootstrap server {sid}...")
                connect_callback(sid)
                _wait_connected(SCAN_BOOTSTRAP_CONNECT_TIMEOUT_S)
                _log("[CONNECT][OK] Bootstrap TUN is ready and verified by the connection worker.")
                if validate_connection_callback and not validate_connection_callback():
                    raise RuntimeError("Bootstrap TUN failed real HTTP validation.")
        except Exception:
            import traceback
            compact = traceback.format_exc().strip().splitlines()[-1]
            _log(f"[CONNECT][ERR] {compact}")
            raise
    else:
        _log(tr(language, "scanner_stage1_skip"))
        already_connected = bool(is_connected_callback and is_connected_callback())
        if already_connected:
            _log("[CONNECT][OK] Reusing the active bootstrap connection.")
        elif connect_callback:
            _log(f"[CONNECT][INFO] Restoring bootstrap server {bootstrap_server_id}...")
            connect_callback(bootstrap_server_id)
            _wait_connected(SCAN_BOOTSTRAP_CONNECT_TIMEOUT_S)
            already_connected = True
        else:
            raise RuntimeError("Existing bootstrap connection is unavailable.")
        if validate_connection_callback and not validate_connection_callback():
            raise RuntimeError("Existing bootstrap TUN failed real HTTP validation.")

    try:
        # --- Stage 2a: Crawl (through the bootstrap VPN) ---------------
        if stage_change:
            stage_change(2, tr(language, "scanner_stage2"))
        socks_port = 0
        if proxy_port_callback:
            try:
                socks_port = max(0, int(proxy_port_callback() or 0))
            except Exception:
                socks_port = 0
        if socks_port:
            _log(
                f"[CONNECT][ROUTE] Telegram uses SOCKS5 127.0.0.1:{socks_port} first; "
                "verified TUN/direct is the fallback"
            )
        else:
            _log("[CONNECT][ROUTE] Telegram uses the verified dicodePing TUN")

        configs = _crawl_only(
            language=language,
            rank1_limit=rank1_limit,
            rank2_limit=rank2_limit,
            stage=stage,
            crawl_progress=crawl_progress,
            eta_callback=eta_callback,
            metrics_callback=metrics_callback,
            log_callback=_log,
            socks_port=socks_port,
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
            _log("[DISCONNECT][START] collected candidates are on disk; stopping dicodePing VPN before tests")
            disconnect_callback()
            _wait_disconnected(SCAN_BOOTSTRAP_DISCONNECT_TIMEOUT_S)
            _log("[DISCONNECT][OK] VPN disconnected and bootstrap process stopped.")

        # --- Stage 2c: Probe (without VPN) ----------------------------
        alive_raws = _probe_only(
            language=language,
            configs=configs,
            stage=stage,
            probe_progress=probe_progress,
            eta_callback=eta_callback,
            alive_count_callback=alive_count_callback,
            metrics_callback=metrics_callback,
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
        source_id = SCANNER_SOURCE_ID
        records: list[ServerRecord] = []
        from .config_profile import classify_config_profile
        for index, (raw, quality) in enumerate(alive, start=1):
            endpoint = parse_endpoint(raw)
            if not endpoint:
                continue
            server_id = record_id(raw)
            clean_raw = set_display_name(raw, f"SUB {index:03d}")
            security = assess_config_security(raw, endpoint.host)
            records.append(
                ServerRecord(
                    id=server_id,
                    name=f"SUB {index:03d}",
                    protocol=endpoint.protocol.upper(),
                    host=endpoint.host,
                    port=endpoint.port,
                    config_blob=config_to_blob(clean_raw),
                    tcp_ms=quality.tcp_ms,
                    ping_ms=quality.ping_ms,
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
                    security_score=security.score,
                    security_level=security.level,
                    security_summary=security.summary,
                )
            )

        _enrich_scanner_records(records, store=store, log=_log)
        raw_lines = [set_display_name(raw, "") for raw, _quality in alive]
        base64_payload = b64_encode_text("\n".join(raw_lines))

        settings = store.load_settings()
        sources_list = list(settings.get("sources") or [])
        sources_list = [
            source for source in sources_list
            if not (isinstance(source, dict) and str(source.get("id") or "").startswith("scanner-"))
        ]
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
            "quality": [
                {
                    "raw": raw,
                    "tcp_ms": quality.tcp_ms,
                    "xray_ms": quality.ping_ms,
                    "ping_ms": quality.ping_ms,
                    "min_ms": quality.min_ms,
                    "avg_ms": quality.avg_ms,
                    "samples_ms": list(quality.samples_ms),
                    "success_count": quality.success_count,
                    "attempts": quality.attempts,
                    "tester": quality.tester,
                }
                for raw, quality in alive
            ],
            "log_lines": state.log_lines,
        }
        # RC5 keeps exactly one scanner subscription and one history item.
        history = [history_record]
        current = store.load_servers()
        by_id = {s.id: s for s in current if not s.source_id.startswith("scanner-")}
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
        for stale in SCANNER_EXPORT_DIR.glob("scanner-*.*"):
            if stale.name not in {f"{source_id}.txt", f"{source_id}.base64.txt"}:
                stale.unlink(missing_ok=True)

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
                _wait_disconnected(SCAN_BOOTSTRAP_DISCONNECT_TIMEOUT_S)
            except Exception as cleanup_error:
                _log(f"[DISCONNECT][ERR] cleanup failed: {cleanup_error}")
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


def delete_scanner_sub(sub_name: str = SCANNER_SOURCE_NAME) -> None:
    del sub_name
    _save_history([])
    for path in (
        SCANNER_EXPORT_DIR / f"{SCANNER_SOURCE_ID}.txt",
        SCANNER_EXPORT_DIR / f"{SCANNER_SOURCE_ID}.base64.txt",
        SCANNER_STAGE1_RAW_FILE,
        SCANNER_STAGE1_META_FILE,
    ):
        path.unlink(missing_ok=True)


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
                    quality = future.result()
                except Exception:
                    quality = None
                if quality is not None and quality.ok and quality.ping_ms is not None:
                    verified.append((int(quality.ping_ms), futures[future]))
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
