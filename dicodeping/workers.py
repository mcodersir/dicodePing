from __future__ import annotations

import concurrent.futures
import os
import subprocess
import threading
import time

from PySide6.QtCore import QThread, Signal

from .constants import HEALTH_URLS
from .diagnostics import get_logger
from .discovery import discover_config_entries
from .i18n import tr
from .models import ServerRecord, SourceDefinition
from .net import is_any_url_reachable_parallel
from .protocols import blob_to_config
from .service import ServerService
from .connection_manager import ConnectionManager
from .xray import XrayManager
from .xray import is_windows
from .updates import check_source_updates, find_application_update
from .sources import normalize_sources
from .constants import RELEASE_VERSION

LOGGER = get_logger("workers")


class TaskCancelled(Exception):
    """Internal cooperative-cancellation signal for background list jobs."""


class ApplicationUpdateThread(QThread):
    """Short network check used by the About page without freezing the UI."""
    ready = Signal(object, object)

    def __init__(self, settings: dict, language: str = "fa") -> None:
        super().__init__()
        self.settings = dict(settings)
        self.language = language

    def run(self) -> None:
        try:
            release = find_application_update(RELEASE_VERSION, "windows" if is_windows() else "linux", timeout=3.0)
            sources = normalize_sources(self.settings, self.language)
            changed, observed = check_source_updates(sources, self.settings.get("source_revisions"))
            self.ready.emit((changed, observed), release)
        except Exception:
            LOGGER.info("Manual update check unavailable", exc_info=True)
            self.ready.emit(([], {}), None)


def _flush_windows_dns() -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _tunnel_passes_real_traffic(manager) -> bool:
    """Validate real internet access after TUN routing is active.

    Xray's StatsService can legitimately return zero during startup on Windows.
    Requiring an immediate counter delta caused healthy tunnels to be rejected.
    The actual routed HTTP requests are therefore authoritative; counters remain
    display-only telemetry.
    """
    if not manager.connected:
        return False
    verifier = getattr(manager, "verify_connection", None)
    if verifier is not None and getattr(manager, "active_core", "xray") != "xray":
        return bool(verifier())
    _flush_windows_dns()
    # Race several endpoints once.  Repeating long 5.5-second probes made a
    # healthy Windows TUN look broken whenever a single public endpoint was
    # filtered or slow.
    # Three bounded rounds cover slower Windows route/DNS propagation without
    # falling back to the old long sequential endpoint checks.
    waits = (0.25, 0.8, 1.6)
    for wait in waits:
        time.sleep(wait)
        if not manager.connected:
            return False
        if is_any_url_reachable_parallel(
            HEALTH_URLS,
            timeout=3.2,
            attempts=1,
            allow_system_proxy=False,
        ):
            return True
    return False


class TaskThread(QThread):
    stage = Signal(str)
    progress = Signal(int, int)
    success = Signal(object)
    failed = Signal(str)

    def emit_progress(self, current: int, total: int) -> None:
        self.checkpoint()
        self.progress.emit(max(0, current), max(total, 1))

    def emit_scaled(self, start: int, end: int, current: int, total: int) -> None:
        self.checkpoint()
        total = max(total, 1)
        ratio = min(1.0, max(0.0, current / total))
        self.progress.emit(int(round(start + (end - start) * ratio)), 100)

    def checkpoint(self) -> None:
        if self.isInterruptionRequested():
            raise TaskCancelled()


class DiscoverThread(TaskThread):
    preview_ready = Signal(object)
    record_updated = Signal(object)

    def __init__(
        self,
        service: ServerService,
        sources: list[SourceDefinition],
        language: str = "fa",
        *,
        preview_only: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.sources = list(sources)
        self.language = language
        self.preview_only = preview_only

    def run(self) -> None:
        try:
            self.checkpoint()
            configs = discover_config_entries(
                self.sources,
                stage=self.stage.emit,
                progress=lambda current, total: self.emit_scaled(0, 22, current, total),
                language=self.language,
            )
            self.checkpoint()
            servers = self.service.build_and_save(
                configs,
                stage=self.stage.emit,
                language=self.language,
                ping_progress=lambda current, total: self.emit_scaled(22, 72, current, total),
                geo_progress=lambda current, total: self.emit_scaled(72, 100, current, total),
                preview_progress=lambda rows: self.preview_ready.emit(rows),
                record_progress=lambda record: self.record_updated.emit(record),
                preview_only=self.preview_only,
            )
            self.checkpoint()
            self.progress.emit(100, 100)
            self.success.emit(servers)
        except TaskCancelled:
            LOGGER.info("Background task cancelled: %s", type(self).__name__)
        except Exception as exc:
            LOGGER.exception("Background task failed: %s", type(self).__name__)
            self.failed.emit(str(exc))


class RefreshThread(TaskThread):
    # A refresh must not make the table look empty.  Individual results are
    # delivered to the UI as they arrive; the final success signal only applies
    # the sorted order.
    record_updated = Signal(object)
    def __init__(self, service: ServerService, language: str = "fa") -> None:
        super().__init__()
        self.service = service
        self.language = language

    def run(self) -> None:
        try:
            self.checkpoint()
            servers = self.service.refresh_saved(
                stage=self.stage.emit,
                language=self.language,
                ping_progress=lambda current, total: self.emit_scaled(0, 68, current, total),
                geo_progress=lambda current, total: self.emit_scaled(68, 100, current, total),
                record_progress=lambda record: self.record_updated.emit(record),
            )
            self.checkpoint()
            self.progress.emit(100, 100)
            self.success.emit(servers)
        except TaskCancelled:
            LOGGER.info("Background task cancelled: %s", type(self).__name__)
        except Exception as exc:
            LOGGER.exception("Background task failed: %s", type(self).__name__)
            self.failed.emit(str(exc))


class RefreshSubsetThread(TaskThread):
    """Re-ping only a subset of saved servers (v1.6.0-rc.4).

    Used by the source-scoped refresh action: when the user has a
    specific source tab active on the Servers page, we only re-probe
    that source's servers instead of the whole list.
    """
    record_updated = Signal(object)

    def __init__(self, service: ServerService, server_ids: list[str], language: str = "fa") -> None:
        super().__init__()
        self.service = service
        self.server_ids = list(server_ids)
        self.language = language

    def run(self) -> None:
        try:
            self.checkpoint()
            servers = self.service.refresh_subset(
                self.server_ids,
                stage=self.stage.emit,
                language=self.language,
                ping_progress=lambda current, total: self.emit_scaled(0, 68, current, total),
                geo_progress=lambda current, total: self.emit_scaled(68, 100, current, total),
            )
            self.checkpoint()
            self.progress.emit(100, 100)
            self.success.emit(servers)
        except TaskCancelled:
            LOGGER.info("Background task cancelled: %s", type(self).__name__)
        except Exception as exc:
            LOGGER.exception("Background task failed: %s", type(self).__name__)
            self.failed.emit(str(exc))


class CoreDownloadThread(QThread):
    """Background worker that downloads an alternative connection core.

    v1.7.0-rc.1: alternative cores (Psiphon, Aether) are not bundled
    with the build.  The user downloads them from inside the app on
    first use.  This thread performs the download, integrity check,
    and extraction off the UI thread.
    """
    stage = Signal(str)
    progress = Signal(int, int)
    success = Signal(str)   # core_id
    failed = Signal(str)    # error message

    def __init__(self, core_id: str, language: str = "fa") -> None:
        super().__init__()
        self.core_id = core_id
        self.language = language

    def run(self) -> None:
        try:
            from .core_manager import download_core
            download_core(
                self.core_id,
                progress=lambda done, total: self.progress.emit(done, total),
                stage=self.stage.emit,
            )
            self.success.emit(self.core_id)
        except Exception as exc:
            LOGGER.exception("Core download failed: %s", self.core_id)
            self.failed.emit(str(exc))


class CoreActivationThread(QThread):
    """Register WARP when needed and persist the selected connection core."""

    stage = Signal(str)
    success = Signal(str)
    failed = Signal(str)

    def __init__(self, core_id: str, *, accept_warp_terms: bool = False, language: str = "fa") -> None:
        super().__init__()
        self.core_id = core_id
        self.accept_warp_terms = bool(accept_warp_terms)
        self.language = language

    def run(self) -> None:
        try:
            if self.core_id == "warp":
                self.stage.emit(
                    "در حال ثبت امن WARP…" if self.language != "en" else "Registering WARP securely…"
                )
                from .connection_manager import register_warp

                register_warp(accept_terms=self.accept_warp_terms)
            self.stage.emit(
                "در حال ذخیره و فعال‌سازی هسته…" if self.language != "en" else "Saving and activating the core…"
            )
            from .core_manager import set_active_core

            set_active_core(self.core_id)
            self.success.emit(self.core_id)
        except Exception as exc:
            LOGGER.exception("Core activation failed: %s", self.core_id)
            self.failed.emit(str(exc))


class SharingThread(QThread):
    completed = Signal(str)

    def __init__(self, *, enable: bool, usb: bool = False, hotspot: bool = False) -> None:
        super().__init__()
        self.enable = enable
        self.usb = usb
        self.hotspot = hotspot

    def run(self) -> None:
        from .vpn_sharing import disable_sharing, enable_sharing
        from .xray import TUN_NAME

        error = (
            enable_sharing(TUN_NAME, usb=self.usb, hotspot=self.hotspot)
            if self.enable
            else disable_sharing(TUN_NAME)
        )
        self.completed.emit(error)


class ScannerThread(QThread):
    """Crash-resistant scanner worker with queued UI requests and batched logs."""

    stage = Signal(str)
    stage_change = Signal(int, str)
    progress = Signal(int, int)
    alive_count = Signal(int)
    eta = Signal(str)  # compatibility only; RC3 does not calculate or display ETA
    metrics = Signal(object)
    log_line = Signal(str)  # compatibility with older integrations
    log_batch = Signal(object)
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    success = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        store,
        language: str = "fa",
        custom_name: str | None = None,
        rank1_limit: int = 3,
        rank2_limit: int = 3,
        connect_callback=None,
        disconnect_callback=None,
        is_connected_callback=None,
        validate_connection_callback=None,
        proxy_port_callback=None,
        bootstrap_server_id: str | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.language = language
        self.custom_name = custom_name
        self.rank1_limit = rank1_limit
        self.rank2_limit = rank2_limit
        # Non-GUI callers may still provide callbacks. The desktop UI leaves
        # these unset and connects to the queued request signals instead.
        self.connect_callback = connect_callback
        self.disconnect_callback = disconnect_callback
        self.is_connected_callback = is_connected_callback
        self.validate_connection_callback = validate_connection_callback
        self.proxy_port_callback = proxy_port_callback
        self.bootstrap_server_id = bootstrap_server_id
        self._stop_event = threading.Event()
        self._log_lock = threading.Lock()
        self._log_buffer: list[str] = []
        self._last_log_flush = time.monotonic()
        self._connection_event = threading.Event()
        self._disconnect_event = threading.Event()
        self._connection_ok = False
        self._connection_message = ""
        self._disconnect_ok = False
        self._disconnect_message = ""

    def requestStop(self) -> None:  # noqa: N802
        self._stop_event.set()
        self.requestInterruption()

    def _request_connect(self, server_id: str) -> None:
        self._connection_ok = False
        self._connection_message = ""
        self._connection_event.clear()
        if self.connect_callback is not None:
            self.connect_callback(server_id)
        else:
            self.connect_requested.emit(server_id)

    def _request_disconnect(self) -> None:
        self._disconnect_ok = False
        self._disconnect_message = ""
        self._disconnect_event.clear()
        if self.disconnect_callback is not None:
            self.disconnect_callback()
        else:
            self.disconnect_requested.emit()

    def notify_connection_result(self, success: bool, message: str = "") -> None:
        self._connection_ok = bool(success)
        self._connection_message = str(message or "")
        self._connection_event.set()

    def notify_disconnected(self, success: bool = True, message: str = "") -> None:
        self._disconnect_ok = bool(success)
        self._disconnect_message = str(message or "")
        self._disconnect_event.set()

    def _wait_for_event(self, event: threading.Event, timeout: float, *, connected: bool) -> tuple[bool, str]:
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if self._stop_event.is_set() or self.isInterruptionRequested():
                return False, "Scanner stopped while waiting for the network operation."
            if event.wait(min(0.15, max(0.01, deadline - time.monotonic()))):
                if connected:
                    return self._connection_ok, self._connection_message
                return self._disconnect_ok, self._disconnect_message
        action = "connection" if connected else "disconnect"
        return False, f"Bootstrap {action} worker did not finish within {int(timeout)} seconds."

    def wait_for_connection(self, timeout: float) -> tuple[bool, str]:
        return self._wait_for_event(self._connection_event, timeout, connected=True)

    def wait_for_disconnect(self, timeout: float) -> tuple[bool, str]:
        return self._wait_for_event(self._disconnect_event, timeout, connected=False)

    def _queue_log(self, line: str) -> None:
        line = str(line).rstrip()
        if not line:
            return
        now = time.monotonic()
        with self._log_lock:
            self._log_buffer.append(line)
            should_flush = len(self._log_buffer) >= 16 or now - self._last_log_flush >= 0.12
        if should_flush:
            self._flush_logs()

    def _flush_logs(self) -> None:
        with self._log_lock:
            if not self._log_buffer:
                return
            rows = tuple(self._log_buffer)
            self._log_buffer.clear()
            self._last_log_flush = time.monotonic()
        self.log_batch.emit(rows)

    def run(self) -> None:
        try:
            from .scanner import run_scan

            result = run_scan(
                store=self.store,
                language=self.language,
                custom_name=self.custom_name,
                rank1_limit=self.rank1_limit,
                rank2_limit=self.rank2_limit,
                stage=self.stage.emit,
                stage_change=self.stage_change.emit,
                crawl_progress=lambda done, total: self.progress.emit(
                    5 + (40 * max(0, done) // max(1, total)), 100
                ),
                probe_progress=lambda done, total: self.progress.emit(
                    50 + (45 * max(0, done) // max(1, total)), 100
                ),
                eta_callback=None,
                alive_count_callback=self.alive_count.emit,
                metrics_callback=self.metrics.emit,
                log_callback=self._queue_log,
                stop_event=self._stop_event,
                connect_callback=self._request_connect,
                disconnect_callback=self._request_disconnect,
                is_connected_callback=self.is_connected_callback,
                validate_connection_callback=self.validate_connection_callback,
                proxy_port_callback=self.proxy_port_callback,
                wait_connected_callback=self.wait_for_connection if self.connect_callback is None else None,
                wait_disconnected_callback=self.wait_for_disconnect if self.disconnect_callback is None else None,
                bootstrap_server_id=self.bootstrap_server_id,
            )
            self._flush_logs()
            self.success.emit(result)
        except Exception as exc:
            self._queue_log(f"[FATAL][ERR] {exc}")
            self._flush_logs()
            LOGGER.exception("Scanner background task failed")
            self.failed.emit(str(exc))


class VolumeFetchThread(QThread):
    """Background worker that refreshes volume info for every saved server.

    The thread re-fetches every source URL's HEAD in parallel to read the
    real ``Subscription-Userinfo`` header, then computes a ``VolumeInfo``
    per server based on the cache (or the remark heuristic as fallback).
    """
    progress = Signal(int, int)
    finished_set = Signal(object)

    def __init__(
        self,
        servers: list[ServerRecord],
        source_urls: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.servers = list(servers)
        self.source_urls = dict(source_urls or {})

    def run(self) -> None:
        try:
            from .volume import fetch_live_volumes
            results = fetch_live_volumes(
                self.servers,
                source_urls=self.source_urls,
                progress=self.progress.emit,
            )
            self.finished_set.emit(results)
        except Exception:
            LOGGER.exception("Volume fetch failed")
            self.finished_set.emit({})


class BestServerSelectionThread(TaskThread):
    """Rank unverified dashboard candidates using real Xray HTTP probes.

    Startup intentionally tests only a sample of each subscription. When that
    sample does not already contain an automatic candidate, this worker gives
    the dashboard button a deterministic, non-blocking path to a real winner.
    """

    def __init__(self, servers: list[ServerRecord], language: str = "fa", limit: int = 10) -> None:
        super().__init__()
        self.language = language
        self.servers = list(servers)[: max(1, min(16, int(limit)))]

    def run(self) -> None:
        from .config_checker import test_config

        try:
            if not self.servers:
                raise RuntimeError(
                    "هیچ سروری برای سنجش وجود ندارد"
                    if self.language != "en" else "No server is available for testing"
                )
            self.stage.emit(
                "در حال انتخاب بهترین سرور با تست واقعی…"
                if self.language != "en" else
                "Selecting the best server with real tunnel tests…"
            )
            ranked: list[tuple[int, ServerRecord]] = []
            workers = min(4, len(self.servers))
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, workers), thread_name_prefix="dicodePing-best"
            ) as pool:
                future_map = {
                    pool.submit(
                        test_config,
                        blob_to_config(server.config_blob),
                        attempts=2,
                        min_success=1,
                        per_attempt_timeout=3.8,
                    ): server
                    for server in self.servers
                    if server.config_blob
                }
                total = len(future_map)
                done = 0
                for future in concurrent.futures.as_completed(future_map):
                    self.checkpoint()
                    server = future_map[future]
                    try:
                        result = future.result()
                    except Exception:
                        result = None
                    done += 1
                    self.progress.emit(done, max(1, total))
                    if result is not None and result.ok and result.ping_ms is not None:
                        server.ping_ms = int(result.ping_ms)
                        server.status = "online"
                        server.failures = 0
                        ranked.append((int(result.ping_ms), server))
            if not ranked:
                raise RuntimeError(
                    "هیچ سروری در تست واقعی پاسخ معتبر نداد"
                    if self.language != "en" else
                    "No server passed the real tunnel test"
                )
            ranked.sort(key=lambda row: (row[0], row[1].failures, row[1].source_order, row[1].name.casefold()))
            self.success.emit([server for _ping, server in ranked])
        except TaskCancelled:
            return
        except Exception as exc:
            LOGGER.exception("Best-server selection failed")
            self.failed.emit(str(exc))


class ConnectThread(TaskThread):
    def __init__(
        self,
        manager: ConnectionManager,
        server: ServerRecord,
        language: str = "fa",
        bypass_domains: list[str] | None = None,
        cdn_domain: str = "",
        secure_dns: bool = False,
        core_options: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.server = server
        self.language = language
        self.bypass_domains = list(bypass_domains or [])
        self.cdn_domain = cdn_domain.strip()
        self.secure_dns = bool(secure_dns)
        self.core_options = dict(core_options or {})

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            self.stage.emit(tr(self.language, "starting_tun"))
            self.progress.emit(6, 100)
            raw_config = (
                blob_to_config(self.server.config_blob)
                if getattr(self.manager, "active_core", "xray") == "xray"
                else ""
            )
            if raw_config and self.cdn_domain:
                from .conn_methods import apply_cdn_formatting
                raw_config = apply_cdn_formatting(raw_config, self.cdn_domain)
            self.manager.start(
                raw_config,
                progress=self.stage.emit,
                language=self.language,
                bypass_domains=self.bypass_domains,
                endpoint_host=self.server.host,
                endpoint_port=self.server.port,
                secure_dns=self.secure_dns,
                core_options=self.core_options,
                progress_value=self.progress.emit,
            )
            if self.isInterruptionRequested():
                self.manager.stop()
                return
            self.progress.emit(94, 100)
            self.stage.emit(tr(self.language, "checking_connection"))
            if not _tunnel_passes_real_traffic(self.manager):
                self.manager.stop()
                raise RuntimeError(
                    "اتصال آماده نشد یا سرور پاسخ اینترنتی معتبر نداد؛ یک سرور دیگر امتحان کنید"
                    if self.language != "en"
                    else "The connection was not ready or the server did not provide valid internet access. Try another server."
                )
            if self.isInterruptionRequested():
                self.manager.stop()
                return
            self.progress.emit(100, 100)
            self.success.emit(self.server)
        except Exception as exc:
            if self.isInterruptionRequested():
                self.manager.stop()
                return
            LOGGER.exception("Background task failed: %s", type(self).__name__)
            self.failed.emit(str(exc))


class ConnectionMonitorThread(QThread):
    updated = Signal(object)
    connection_lost = Signal()

    def __init__(self, manager: XrayManager) -> None:
        super().__init__()
        self.manager = manager

    def run(self) -> None:
        last_ping: int | None = None
        last_upload = 0
        last_download = 0
        next_stats = 0.0
        next_ping = 0.0

        while not self.isInterruptionRequested() and self.manager.connected:
            now = time.monotonic()
            changed = False

            if now >= next_stats:
                upload, download = self.manager.traffic_stats()
                if isinstance(upload, int) and upload >= last_upload and upload != last_upload:
                    last_upload = upload
                    changed = True
                if isinstance(download, int) and download >= last_download and download != last_download:
                    last_download = download
                    changed = True
                next_stats = now + 2.5

            if now >= next_ping:
                ping = self.manager.connected_ping(timeout=0.8)
                if ping != last_ping:
                    last_ping = ping
                    changed = True
                next_ping = now + 12.0

            if changed:
                self.updated.emit({"upload": last_upload, "download": last_download, "ping": last_ping})

            connection_ended = False
            for _ in range(4):
                if self.isInterruptionRequested():
                    return
                if not self.manager.connected:
                    connection_ended = True
                    break
                self.msleep(50)
            if connection_ended:
                break
        if not self.isInterruptionRequested() and not self.manager.connected:
            self.connection_lost.emit()
