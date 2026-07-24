from __future__ import annotations

import concurrent.futures
import socket
import time
from collections import defaultdict

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QBoxLayout, QHeaderView

from . import net as net_module
from . import service as service_module
from . import xray as xray_module
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
    # Host latency cannot prove that a config's protocol, credentials and
    # transport work. Only publish a number after real HTTP traffic traverses
    # that exact Xray outbound, matching the useful-delay semantics of v2rayNG.
    rows = [row for row in records if row.host]
    hosts = list(dict.fromkeys(row.host for row in rows))
    # Resolve addresses for location lookup, but do not run a separate ICMP
    # measurement. It was both redundant and misleading because a reachable
    # host does not mean that this particular config is usable.
    resolver = concurrent.futures.ThreadPoolExecutor(max_workers=min(32, max(1, len(hosts))))
    resolution_futures = {resolver.submit(net_module.resolve_ipv4, host): host for host in hosts}
    address_results: dict[str, str] = {}
    done_futures, pending_futures = concurrent.futures.wait(
        resolution_futures,
        timeout=6.0,
        return_when=concurrent.futures.ALL_COMPLETED,
    )
    for future in done_futures:
        host = resolution_futures[future]
        try:
            address_results[host] = future.result()
        except Exception:
            address_results[host] = ""
    for future in pending_futures:
        future.cancel()
    resolver.shutdown(wait=False, cancel_futures=True)
    for row in rows:
        address = address_results.get(row.host, "")
        if address:
            row.ip = address

    timeout_ms = bounded_int(settings.get("test_timeout_ms"), 3000, 1500, 5000)
    timeout = max(2.5, timeout_ms / 1000.0)
    # v2rayNG tests a batch concurrently (16 by default). The previous cap of
    # eight made large subscriptions unnecessarily slow even when the UI asked
    # for more workers.
    concurrency = bounded_int(settings.get("test_concurrency"), 16, 4, 32)

    def needs_tcp_precheck(row: ServerRecord) -> bool:
        try:
            outbound = xray_module.build_xray_outbound(blob_to_config(row.config_blob)) or {}
            protocol = str(outbound.get("protocol", "")).lower()
            stream = outbound.get("streamSettings", {})
            network = str(stream.get("network", "tcp")).lower() if isinstance(stream, dict) else "tcp"
            return protocol not in {"hysteria2", "wireguard", "tuic"} and network not in {
                "kcp", "quic", "hysteria2", "wireguard"
            }
        except Exception:
            return False

    def tcp_reachable(row: ServerRecord) -> bool:
        target = row.ip or row.host
        try:
            with socket.create_connection((target, row.port), timeout=1.0):
                return True
        except OSError:
            return False

    def probe(row: ServerRecord, probe_timeout: float) -> int | None:
        try:
            # Fast rejection mirrors v2rayNG's ordinary-config TCP pre-check;
            # this number is never shown as the server ping.
            if needs_tcp_precheck(row) and not tcp_reachable(row):
                return None
            return xray_module.probe_outbound_delay(blob_to_config(row.config_blob), timeout=probe_timeout)
        except Exception:
            return None

    def apply_row(row: ServerRecord, latency: int | None) -> None:
        now = service_module.utc_now()
        row.last_checked = now
        if trusted_latency(latency):
            row.ping_ms, row.status, row.failures = latency, "online", 0
        else:
            row.ping_ms, row.status, row.failures = None, "unverified", row.failures + 1
        if record_callback:
            record_callback(row)

    failed: list[ServerRecord] = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(probe, row, timeout): row for row in rows}
        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            try:
                latency = future.result()
            except Exception:
                latency = None
            apply_row(row, latency)
            if latency is None:
                failed.append(row)
            done += 1
            if callback:
                callback(done, len(rows))

    if settings.get("retry_failed_tests", True) and failed:
        retry_rows = failed[:6]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(retry_rows))) as pool:
            futures = {pool.submit(probe, row, max(3.5, timeout)): row for row in retry_rows}
            for future in concurrent.futures.as_completed(futures):
                row = futures[future]
                try:
                    latency = future.result()
                except Exception:
                    latency = None
                if latency is not None:
                    apply_row(row, latency)

    return records


def _apply_geo(service, records, callback=None, record_callback=None):
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
        if record_callback:
            record_callback(row)


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
                ping_ms=previous.ping_ms if previous else None,
                ip=previous.ip if previous else "",
                country=previous.country if previous else ("Unknown" if kwargs.get("language") == "en" else "نامشخص"),
                country_code=previous.country_code if previous else "",
                region=previous.region if previous else "",
                city=previous.city if previous else "",
                isp=previous.isp if previous else "",
                asn=previous.asn if previous else "",
                geo_provider=previous.geo_provider if previous else "",
                geo_confidence=previous.geo_confidence if previous else "",
                status=previous.status if previous else "unverified",
            ))
            if len(records) >= 320:
                break
        if not records:
            raise RuntimeError("No usable server was received" if kwargs.get("language") == "en" else "هیچ سرور قابل استفاده‌ای دریافت نشد")
        # Parsed configs are already useful. Persist and expose them before DNS,
        # latency and location enrichment so the UI can leave its skeleton even
        # when a resolver/provider is slow or unavailable.
        self.store.save_servers(records)
        if kwargs.get("preview_progress"):
            kwargs["preview_progress"](list(records))
        if kwargs.get("preview_only"):
            return records
        if kwargs.get("stage"):
            kwargs["stage"](service_module.tr(kwargs.get("language", "fa"), "testing_ping"))
        _test_records(
            records,
            self.store.load_settings(),
            kwargs.get("ping_progress") or kwargs.get("progress"),
            kwargs.get("record_progress"),
        )
        if kwargs.get("stage"):
            kwargs["stage"](service_module.tr(kwargs.get("language", "fa"), "resolving_location"))
        _apply_geo(
            self,
            records,
            kwargs.get("geo_progress") or kwargs.get("progress"),
            kwargs.get("record_progress"),
        )
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
        _apply_geo(
            self,
            records,
            kwargs.get("geo_progress") or kwargs.get("progress"),
            kwargs.get("record_progress"),
        )
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
