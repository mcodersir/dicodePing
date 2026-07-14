from __future__ import annotations

import concurrent.futures
import socket
import time
from collections import defaultdict

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QBoxLayout, QHeaderView

from . import net as net_module
from . import service as service_module
from .models import DiscoveredConfig, ServerRecord
from .protocols import blob_to_config, config_to_blob, normalize_key, parse_endpoint, record_id
from .rc2_core import extract_display_name
from .rc3_core import median_latency, trusted_latency
from .rc7_core import batches, bounded_int, diverse_auto_candidates

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


def _test_records(records: list[ServerRecord], settings: dict, callback=None) -> list[ServerRecord]:
    concurrency = bounded_int(settings.get("test_concurrency"), 28, 4, 48)
    page_size = bounded_int(settings.get("test_batch_size"), 48, 8, 96)
    timeout = bounded_int(settings.get("test_timeout_ms"), 950, 400, 3000) / 1000.0
    retry_failed = bool(settings.get("retry_failed_tests", True))
    by_endpoint: dict[tuple[str, int], list[ServerRecord]] = defaultdict(list)
    for row in records:
        if row.host and row.port:
            by_endpoint[(row.host, row.port)].append(row)
    endpoints = list(by_endpoint)
    hosts = list(dict.fromkeys(host for host, _ in endpoints))
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, len(hosts) or 1)) as resolver_pool:
        host_results = dict(zip(hosts, resolver_pool.map(lambda host: net_module.resolve_all_ips(host)[:2], hosts)))
    resolved = {key: host_results.get(key[0], []) for key in endpoints}
    routes = net_module.install_direct_host_routes(ip for values in resolved.values() for ip in values if ":" not in ip)
    results: dict[tuple[str, int], tuple[int | None, str]] = {}
    done = 0

    def run_page(page, workers, attempt_timeout):
        nonlocal done
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(page) or 1)) as pool:
            futures = {
                pool.submit(_probe, host, port, resolved[(host, port)], attempt_timeout): (host, port)
                for host, port in page
            }
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception:
                    results[key] = (None, resolved[key][0] if resolved[key] else "")
                done += 1
                if callback:
                    callback(min(done, len(endpoints)), max(1, len(endpoints)))

    try:
        for page in batches(endpoints, page_size):
            run_page(page, concurrency, timeout)
        failed = [key for key in endpoints if results.get(key, (None, ""))[0] is None]
        if retry_failed and failed:
            # Like v2rayN: retry the failed portion with smaller pages/concurrency.
            for page in batches(failed, max(4, page_size // 2)):
                run_page(page, max(3, concurrency // 2), min(3.0, timeout * 1.5))
    finally:
        net_module.remove_direct_host_routes(routes)

    now = service_module.utc_now()
    for endpoint, rows in by_endpoint.items():
        latency, ip = results.get(endpoint, (None, ""))
        for row in rows:
            row.last_checked = now
            row.ip = ip or row.ip
            if trusted_latency(latency):
                row.ping_ms, row.status, row.failures = latency, "online", 0
            else:
                row.ping_ms, row.status, row.failures = None, "unverified", row.failures + 1
    return records


def _apply_geo(service, records, callback=None):
    ips = list(dict.fromkeys(row.ip for row in records if row.ip))
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
        _test_records(records, self.store.load_settings(), kwargs.get("ping_progress") or kwargs.get("progress"))
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
        eligible = [row for row in values if row.status == "online" and trusted_latency(row.ping_ms)]
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
        QApplication.instance().installEventFilter(self)
        self.table.setTextElideMode(Qt.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 112)
        header.setMinimumSectionSize(72)
        self.settings_tabs.tabBar().setUsesScrollButtons(True)
        self.settings_tabs.tabBar().setElideMode(Qt.ElideRight)

    def event_filter(self, obj, event):
        if self.isMaximized() or not hasattr(obj, "window") or obj.window() is not self:
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
            full = label.toolTip() or label.text()
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
        QApplication.instance().removeEventFilter(self)
        original_close(self, event)

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
