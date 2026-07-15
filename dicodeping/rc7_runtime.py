from __future__ import annotations

import socket
import time
from collections import defaultdict

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QBoxLayout, QHeaderView

from . import net as net_module
from . import service as service_module
from .models import DiscoveredConfig, ServerRecord
from .protocols import blob_to_config, config_to_blob, normalize_key, parse_endpoint, record_id
from .rc2_core import extract_display_name
from .rc3_core import median_latency, trusted_latency
from .rc7_core import batches, bounded_int, diverse_auto_candidates
from .rc8_core import geo_lookup_ips, unresolved_retry_hosts

_PATCHED = False


def _probe(host: str, port: int, addresses: list[str], timeout: float) -> tuple[int | None, str]:
    choices: list[tuple[int, str]] = []
    for ip in addresses[:2]:
        samples: list[int] = []
        for _ in range(2):
            started = time.perf_counter()
            try:
                with socket.create_connection((ip, port), timeout=timeout):
                    samples.append(max(1, round((time.perf_counter() - started) * 1000)))
            except OSError:
                break
        latency = median_latency(samples)
        if latency is not None:
            choices.append((latency, ip))
    return min(choices, default=(None, addresses[0] if addresses else ""), key=lambda item: item[0] or 999_999)


def _test_records(records: list[ServerRecord], settings: dict, callback=None, record_callback=None) -> list[ServerRecord]:
    # The server list is a latency view, not a connection test.  Starting a
    # temporary core for every item included startup/proxy negotiation in the
    # number and produced inflated, unstable values.  Measure ICMP Echo
    # directly, once per host, exactly as the native Windows ping path does.
    # A real connection is still validated only when the user connects.
    del settings
    rows = [row for row in records if row.host]
    hosts = list(dict.fromkeys(row.host for row in rows))
    results = {
        item.key: item
        for item in net_module.ping_many(
            [(host, host) for host in hosts], workers=min(64, max(1, len(hosts))), callback=callback
        )
    }

    def apply_row(row: ServerRecord) -> None:
        result = results.get(row.host)
        latency = result.ping_ms if result else None
        now = service_module.utc_now()
        row.last_checked = now
        if trusted_latency(latency):
            if result and result.ip and result.ip != "dns":
                row.ip = result.ip
            row.ping_ms, row.status, row.failures = latency, "online", 0
        else:
            row.ping_ms, row.status, row.failures = None, "unverified", row.failures + 1
        if record_callback:
            record_callback(row)

    for row in rows:
        apply_row(row)

    return records


def _apply_geo(service, records, callback=None):
    # Looking up dead rows added dozens of slow public requests without adding
    # useful information to the UI. Cached location stays intact on failures.
    ips = geo_lookup_ips(records)
    located = service.geo.resolve_many(ips, callback=callback)
    for row in records:
        data = located.get(row.ip, {})
        for field in ("country", "country_code", "region", "city", "isp", "asn", "geo_provider", "geo_confidence"):
            value = data.get(field)
            if value:
                setattr(row, field, str(value).upper() if field == "country_code" else str(value))


def _install_service_patch() -> None:
    def build(self, raw_configs, *args, **kwargs):
        entries = [item if isinstance(item, DiscoveredConfig) else DiscoveredConfig(str(item), "default", "", 0) for item in raw_configs]
        old = {row.id: row for row in self.store.load_servers()}
        records: list[ServerRecord] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            endpoint = parse_endpoint(entry.raw)
            key = normalize_key(entry.raw)
            if not endpoint or not key or key in seen:
                continue
            seen.add(key)
            sid = record_id(entry.raw)
            previous = old.get(sid)
            name = extract_display_name(entry.raw) or (f"Server {len(records) + 1:02d}" if kwargs.get("language") == "en" else f"سرور {len(records) + 1:02d}")
            records.append(ServerRecord(
                id=sid, name=name, protocol=endpoint.protocol.upper(), host=endpoint.host,
                port=endpoint.port, config_blob=config_to_blob(entry.raw), source_id=entry.source_id,
                source_name=entry.source_name, source_order=entry.source_order,
                favorite=previous.favorite if previous else False,
                last_connected=previous.last_connected if previous else "",
            ))
            if len(records) >= 320:
                break
        if not records:
            raise RuntimeError("No usable server was received" if kwargs.get("language") == "en" else "هیچ سرور قابل استفاده‌ای دریافت نشد")
        if kwargs.get("stage"):
            kwargs["stage"](service_module.tr(kwargs.get("language", "fa"), "testing_ping"))
        _test_records(records, self.store.load_settings(), kwargs.get("ping_progress") or kwargs.get("progress"))
        if kwargs.get("stage"):
            kwargs["stage"](service_module.tr(kwargs.get("language", "fa"), "resolving_location"))
        _apply_geo(self, records, kwargs.get("geo_progress") or kwargs.get("progress"))
        records.sort(key=service_module._sort_key)
        self.store.save_servers(records)
        return records

    def refresh(self, *args, **kwargs):
        records = self.store.load_servers()
        _test_records(
            records,
            self.store.load_settings(),
            kwargs.get("ping_progress") or kwargs.get("progress"),
            kwargs.get("record_progress"),
        )
        _apply_geo(self, records, kwargs.get("geo_progress") or kwargs.get("progress"))
        for row in records:
            try:
                row.name = extract_display_name(blob_to_config(row.config_blob)) or row.name
            except Exception:
                pass
        records.sort(key=service_module._sort_key)
        self.store.save_servers(records)
        return records

    def auto_candidates(self, records=None):
        values = records if records is not None else self.store.load_servers()
        # Keep the service policy as the single source of truth: it rejects
        # sub-70 ms samples, missing locations and restricted locations.
        eligible = [
            row for row in values
            if (
                row.status == "online"
                and service_module.MIN_TRUSTED_AUTO_PING_MS <= int(row.ping_ms or 0) <= service_module.MAX_TRUSTED_AUTO_PING_MS
                and not service_module.is_restricted_location(row)
            )
        ]
        return diverse_auto_candidates(eligible, limit=12)

    service_module.ServerService.build_and_save = build
    service_module.ServerService.refresh_saved = refresh
    service_module.ServerService.auto_candidates = auto_candidates


def _install_ui_patch() -> None:
    from .ui import AppDialog, MainWindow

    original_init = MainWindow.__init__
    original_resize = MainWindow.resizeEvent
    original_render = MainWindow.render_servers
    original_summary = MainWindow._render_home_summary
    original_save = MainWindow.save_settings_page
    original_close = MainWindow.closeEvent

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.setMinimumSize(600, 440)
        # Installing this on QApplication made every widget event re-enter the
        # filter. Calling obj.window() from that global hook can recurse on
        # PySide6 6.10 and crash the process during its first show event.
        # The native resize affordance only needs events from this window.
        self.installEventFilter(self)
        self.table.setTextElideMode(Qt.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 112)
        header.setMinimumSectionSize(72)
        # Keep Persian settings tabs visible instead of collapsing the first
        # tab into the right-side overflow button.
        settings_bar = self.settings_tabs.tabBar()
        settings_bar.setUsesScrollButtons(False)
        settings_bar.setExpanding(True)
        settings_bar.setElideMode(Qt.ElideNone)

    def event_filter(self, obj, event):
        if self.isMaximized() or obj is not self:
            return False
        if event.type() not in (QEvent.MouseMove, QEvent.MouseButtonPress):
            return False
        pos = self.mapFromGlobal(event.globalPosition().toPoint())
        pad = 7
        edges = Qt.Edges()
        if pos.x() <= pad: edges |= Qt.LeftEdge
        elif pos.x() >= self.width() - pad: edges |= Qt.RightEdge
        if pos.y() <= pad: edges |= Qt.TopEdge
        elif pos.y() >= self.height() - pad: edges |= Qt.BottomEdge
        if not edges:
            return False
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            handle = self.windowHandle()
            return bool(handle and handle.startSystemResize(edges))
        return False

    def resize(self, event):
        original_resize(self, event)
        width = event.size().width()
        if hasattr(self, "table"):
            self.table.setColumnHidden(3, width < 980)
            self.table.setColumnHidden(2, width < 790)
            self.table.setColumnHidden(5, width < 740)
        compact = width < 850
        for name in ("settings_mode_row", "source_input_row", "settings_appearance_row"):
            layout = getattr(self, name, None)
            if layout:
                layout.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
        if hasattr(self, "server_header_layout"):
            # The subtitle needs its own full row before the action buttons.
            self.server_header_layout.setDirection(QBoxLayout.TopToBottom if width < 1160 else QBoxLayout.LeftToRight)
        summary(self)

    def render(self):
        original_render(self)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item:
                item.setToolTip(item.text())

    def summary(self):
        original_summary(self)
        label = getattr(self, "home_best_name", None)
        if label and label.text():
            # original_summary just wrote the current full name. A previous
            # tooltip must never override a newly selected server.
            full = label.text()
            label.setToolTip(full)
            width = max(120, label.width() - 8)
            label.setText(QFontMetrics(label.font()).elidedText(full, Qt.ElideRight, width))

    def connect_best(self):
        if self.worker or self.manager.connected:
            return
        limit = bounded_int(self.settings.get("auto_retry_limit"), 8, 2, 12)
        queue = [row.id for row in self.service.auto_candidates(self.servers)[:limit]]
        if not queue:
            AppDialog.info(self, self.t("no_healthy_title"), self.t("need_refresh"), self.t("ok"))
            return
        self._rc5_auto_active, self._rc5_auto_queue = True, queue
        self._rc5_auto_errors, self._rc5_attempting_id = [], ""
        self._rc5_try_next_auto()

    def save(self):
        original_save(self)
        from .diagnostics import configure_logging
        configure_logging(bool(self.settings.get("diagnostic_logging", False)), str(self.settings.get("log_level", "INFO")))

    def close(self, event):
        original_close(self, event)
        if event.isAccepted():
            self.removeEventFilter(self)

    MainWindow.__init__ = init
    MainWindow.eventFilter = event_filter
    MainWindow.resizeEvent = resize
    MainWindow.render_servers = render
    MainWindow._render_home_summary = summary
    MainWindow.connect_best = connect_best
    MainWindow.save_settings_page = save
    MainWindow.closeEvent = close


def install_rc7_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_service_patch()
    _install_ui_patch()
