from __future__ import annotations

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


def _tunnel_passes_real_traffic(manager: XrayManager) -> bool:
    """Validate real internet access after TUN routing is active.

    Xray's StatsService can legitimately return zero during startup on Windows.
    Requiring an immediate counter delta caused healthy tunnels to be rejected.
    The actual routed HTTP requests are therefore authoritative; counters remain
    display-only telemetry.
    """
    if not manager.connected:
        return False
    _flush_windows_dns()
    # Race several endpoints once.  Repeating long 5.5-second probes made a
    # healthy Windows TUN look broken whenever a single public endpoint was
    # filtered or slow.
    # Two short rounds are enough to cover Windows route propagation. The old
    # three-round sequence could hold every failed auto candidate for ~12 s.
    waits = (0.25, 0.7)
    for wait in waits:
        time.sleep(wait)
        if not manager.connected:
            return False
        if is_any_url_reachable_parallel(
            HEALTH_URLS,
            timeout=2.6,
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


class ScannerThread(QThread):
    """Background worker that runs the staged one-click scanner.

    Signals:
      stage — current stage status text.
      stage_change — (stage_number, stage_label) when the stage advances.
      progress — (current, total) probe count.
      alive_count — emitted whenever the live healthy-server count changes.
      eta — formatted ETA string.
      log_line — live log line for the scanner log panel.
      success — ScannerResult on completion.
      failed — localized error message on failure.
    """
    stage = Signal(str)
    stage_change = Signal(int, str)
    progress = Signal(int, int)
    alive_count = Signal(int)
    eta = Signal(str)
    log_line = Signal(str)
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
        bootstrap_server_id: str | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.language = language
        self.custom_name = custom_name
        self.rank1_limit = rank1_limit
        self.rank2_limit = rank2_limit
        self.connect_callback = connect_callback
        self.disconnect_callback = disconnect_callback
        self.is_connected_callback = is_connected_callback
        self.bootstrap_server_id = bootstrap_server_id
        self._stop_event = threading.Event()

    def requestStop(self) -> None:  # noqa: N802
        self._stop_event.set()

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
                crawl_progress=lambda _d, _t: None,
                probe_progress=self.progress.emit,
                eta_callback=self.eta.emit,
                alive_count_callback=self.alive_count.emit,
                log_callback=self.log_line.emit,
                stop_event=self._stop_event,
                connect_callback=self.connect_callback,
                disconnect_callback=self.disconnect_callback,
                is_connected_callback=self.is_connected_callback,
                bootstrap_server_id=self.bootstrap_server_id,
            )
            self.success.emit(result)
        except Exception as exc:
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


class ConnectThread(TaskThread):
    def __init__(
        self,
        manager: XrayManager,
        server: ServerRecord,
        language: str = "fa",
        bypass_domains: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.server = server
        self.language = language
        self.bypass_domains = list(bypass_domains or [])

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            self.stage.emit(tr(self.language, "starting_tun"))
            self.progress.emit(20, 100)
            self.manager.start(
                blob_to_config(self.server.config_blob),
                progress=self.stage.emit,
                language=self.language,
                bypass_domains=self.bypass_domains,
                endpoint_host=self.server.host,
                endpoint_port=self.server.port,
            )
            if self.isInterruptionRequested():
                self.manager.stop()
                return
            self.progress.emit(72, 100)
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
                if upload >= last_upload and upload != last_upload:
                    last_upload = upload
                    changed = True
                if download >= last_download and download != last_download:
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
