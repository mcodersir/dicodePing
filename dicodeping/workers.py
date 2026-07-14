from __future__ import annotations

import os
import subprocess
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

LOGGER = get_logger("workers")


class TaskCancelled(Exception):
    """Internal cooperative-cancellation signal for background list jobs."""


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
        if is_any_url_reachable_parallel(HEALTH_URLS, timeout=2.6, attempts=1):
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
    def __init__(self, service: ServerService, sources: list[SourceDefinition], language: str = "fa") -> None:
        super().__init__()
        self.service = service
        self.sources = list(sources)
        self.language = language

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
            )
            self.checkpoint()
            self.progress.emit(100, 100)
            self.success.emit(servers)
        except TaskCancelled:
            LOGGER.info("Background task cancelled: %s", type(self).__name__)
        except Exception as exc:
            LOGGER.exception("Background task failed: %s", type(self).__name__)
            self.failed.emit(str(exc))


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
