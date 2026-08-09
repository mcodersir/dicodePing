from __future__ import annotations

import concurrent.futures
import hashlib
import math
import socket
import time
from collections import defaultdict

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


def _resolve_record_ips(records: list[ServerRecord], record_callback=None) -> None:
    """Resolve each host once and publish IPs before enrichment starts."""
    rows = [row for row in records if row.host and row.port]
    hosts = list(dict.fromkeys(row.host for row in rows))
    if not hosts:
        return
    address_results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, max(1, len(hosts)))) as resolver:
        futures = {resolver.submit(net_module.resolve_ipv4, host): host for host in hosts}
        for future in concurrent.futures.as_completed(futures):
            host = futures[future]
            try:
                address_results[host] = future.result()
            except Exception:
                address_results[host] = ""
    for row in rows:
        address = address_results.get(row.host, "")
        if address:
            row.ip = address
            if record_callback:
                record_callback(row)


def _test_records(
    records: list[ServerRecord],
    settings: dict,
    callback=None,
    record_callback=None,
    *,
    resolve_ips: bool = True,
) -> list[ServerRecord]:
    """Measure saved configurations with a fast TCP gate and real Xray HTTP.

    DNS is shared with geolocation, dead TCP endpoints never spawn an expensive
    Xray process, and responsive rows are tested concurrently with bounded
    workers.
    """
    rows = [row for row in records if row.host and row.port]
    if not rows:
        return records
    if resolve_ips:
        # DNS is delegated to _resolve_record_ips, which uses net_module.resolve_ipv4.
        _resolve_record_ips(rows, record_callback=record_callback)

    timeout_ms = bounded_int(settings.get("test_timeout_ms"), 2600, 1200, 7000)
    xray_timeout = max(2.0, timeout_ms / 1000.0)
    tcp_timeout = min(1.25, max(0.55, xray_timeout * 0.35))
    concurrency = bounded_int(settings.get("test_concurrency"), 24, 4, 48)

    def measure(row: ServerRecord) -> tuple[int | None, int | None]:
        target = row.ip or row.host
        started = time.perf_counter()
        try:
            with socket.create_connection((target, int(row.port)), timeout=tcp_timeout):
                tcp_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
        except OSError:
            return None, None
        try:
            xray_ms = xray_module.probe_outbound_delay(
                blob_to_config(row.config_blob),
                timeout=xray_timeout,
            )
            xray_ms = int(xray_ms) if trusted_latency(xray_ms) else None
        except Exception:
            xray_ms = None
        return tcp_ms, xray_ms

    def apply_row(row: ServerRecord, tcp_ms: int | None, xray_ms: int | None) -> None:
        row.last_checked = service_module.utc_now()
        row.tcp_ms = tcp_ms
        row.icmp_ms = None
        if trusted_latency(xray_ms):
            row.ping_ms, row.status, row.failures = int(xray_ms), "online", 0
        else:
            row.ping_ms, row.status, row.failures = None, "unverified", row.failures + 1
        if record_callback:
            record_callback(row)

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(measure, row): row for row in rows}
        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            try:
                tcp_ms, xray_ms = future.result()
            except Exception:
                tcp_ms, xray_ms = None, None
            apply_row(row, tcp_ms, xray_ms)
            done += 1
            if callback:
                callback(done, len(rows))
    return records


def _apply_geo(service, records, callback=None, record_callback=None):
    """Resolve locations independently and stream each completed IP."""
    rows_by_ip: dict[str, list[ServerRecord]] = defaultdict(list)
    for row in records:
        if row.ip and row.ip != "dns":
            rows_by_ip[row.ip].append(row)
    ips = list(rows_by_ip)

    def apply_ip(ip: str, data: dict[str, str]) -> None:
        for row in rows_by_ip.get(ip, []):
            for field in ("country", "country_code", "region", "city", "isp", "asn", "geo_provider", "geo_confidence"):
                value = data.get(field)
                if value:
                    setattr(row, field, str(value).upper() if field == "country_code" else str(value))
            if record_callback:
                record_callback(row)

    located = service.geo.resolve_many(
        ips,
        callback=callback,
        fast=True,
        result_callback=apply_ip,
    )
    for ip, data in located.items():
        apply_ip(ip, data)
    return records


def _enrich_records_parallel(
    service,
    records: list[ServerRecord],
    settings: dict,
    ping_callback=None,
    geo_callback=None,
    record_callback=None,
) -> list[ServerRecord]:
    """Run real proxy tests and geolocation at the same time."""
    _resolve_record_ips(records, record_callback=record_callback)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ping_future = pool.submit(
            _test_records, records, settings, ping_callback, record_callback, resolve_ips=False
        )
        geo_future = pool.submit(
            _apply_geo, service, records, None, record_callback
        )
        ping_future.result()
        geo_future.result()
    if geo_callback:
        geo_callback(1, 1)
    return records


def _sample_records_by_source(records: list[ServerRecord], ratio: float = 0.30) -> list[ServerRecord]:
    """Return a deterministic per-subscription sample for splash probing.

    Every non-empty source contributes at least one row. Stable hashing avoids
    repeatedly testing only the first entries while keeping startup behavior
    reproducible across platforms.
    """
    ratio = max(0.01, min(1.0, float(ratio)))
    grouped: dict[str, list[ServerRecord]] = defaultdict(list)
    for row in records:
        grouped[row.source_id or "default"].append(row)
    sampled: list[ServerRecord] = []
    for source_id in sorted(grouped):
        rows = grouped[source_id]
        rows.sort(
            key=lambda row: hashlib.sha256(
                f"{source_id}:{row.id}".encode("utf-8", errors="ignore")
            ).digest()
        )
        take = max(1, int(math.ceil(len(rows) * ratio)))
        sampled.extend(rows[:take])
    return sampled



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
                tcp_ms=previous.tcp_ms if previous else None,
                ping_ms=previous.ping_ms if previous else None,
                icmp_ms=previous.icmp_ms if previous else None,
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
        sample_ratio = kwargs.get("ping_sample_ratio")
        probe_records = (
            _sample_records_by_source(records, float(sample_ratio))
            if sample_ratio is not None and float(sample_ratio) < 1.0
            else records
        )
        if kwargs.get("stage"):
            kwargs["stage"](service_module.tr(kwargs.get("language", "fa"), "testing_ping"))
        _enrich_records_parallel(
            self,
            probe_records,
            self.store.load_settings(),
            kwargs.get("ping_progress") or kwargs.get("progress"),
            kwargs.get("geo_progress") or kwargs.get("progress"),
            kwargs.get("record_progress"),
        )
        records.sort(key=service_module._sort_key)
        self.store.save_servers(records)
        return records

    def refresh(self, *args, **kwargs):
        records = self.store.load_servers()
        _enrich_records_parallel(
            self,
            records,
            self.store.load_settings(),
            kwargs.get("ping_progress") or kwargs.get("progress"),
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

    def refresh_sampled(self, ratio=0.30, *args, **kwargs):
        records = self.store.load_servers()
        if not records:
            return []
        sampled = _sample_records_by_source(records, ratio)
        if kwargs.get("stage"):
            kwargs["stage"](service_module.tr(kwargs.get("language", "fa"), "testing_ping"))
        _enrich_records_parallel(
            self,
            sampled,
            self.store.load_settings(),
            kwargs.get("ping_progress") or kwargs.get("progress"),
            kwargs.get("geo_progress") or kwargs.get("progress"),
            kwargs.get("record_progress"),
        )
        records.sort(key=service_module._sort_key)
        self.store.save_servers(records)
        return records

    def refresh_subset(self, server_ids, *args, **kwargs):
        target_ids = set(server_ids)
        records = self.store.load_servers()
        subset = [row for row in records if row.id in target_ids]
        if not subset:
            return records
        _enrich_records_parallel(
            self,
            subset,
            self.store.load_settings(),
            kwargs.get("ping_progress") or kwargs.get("progress"),
            kwargs.get("geo_progress") or kwargs.get("progress"),
            kwargs.get("record_progress"),
        )
        records.sort(key=service_module._sort_key)
        self.store.save_servers(records)
        return records

    def auto_candidates(self, records=None):
        values = records if records is not None else self.store.load_servers()
        # Automatic mode accepts every positive real HTTP-probe result,
        # rejects restricted locations, applies bounded failure penalties and
        # diversifies candidates by endpoint before sequential verification.
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
    service_module.ServerService.refresh_sampled = refresh_sampled
    service_module.ServerService.refresh_subset = refresh_subset
    service_module.ServerService.auto_candidates = auto_candidates


def _install_ui_patch() -> None:
    # Keep the network/runtime module importable on headless Linux CI hosts.
    # QtGui loads EGL at import time on Linux, while the connectivity helpers
    # above do not need any GUI classes. Import Qt only when UI patching is
    # actually installed by the desktop application.
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QBoxLayout, QHeaderView

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
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        self.table.setColumnWidth(8, 124)
        header.setMinimumSectionSize(72)
        # Keep Persian settings tabs visible instead of collapsing the first
        # tab into the right-side overflow button.
        settings_bar = self.settings_tabs.tabBar()
        settings_bar.setUsesScrollButtons(True)
        settings_bar.setExpanding(False)
        settings_bar.setElideMode(Qt.ElideRight)
        self._best_selection_thread = None
        self._best_selection_result = []
        self._best_selection_error = ""

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
        known = list(self.service.auto_candidates(self.servers)[:limit])
        if known:
            self._auto_connect_queue = list(known[1:])
            self.connect_server(known[0], automatic=True)
            return

        # Only 30% of each subscription is tested during splash. If that sample
        # did not produce a trusted winner, rank a bounded candidate set here
        # with real Xray HTTP probes instead of leaving the dashboard inert.
        candidates = [
            row for row in self.servers
            if row.config_blob and not self.service.is_restricted_location(row)
        ]
        candidates.sort(
            key=lambda row: (
                0 if row.status == "online" else 1,
                row.ping_ms is None,
                row.ping_ms or 999_999,
                row.failures,
                row.source_order,
                row.name.casefold(),
            )
        )
        candidates = candidates[:limit]
        if not candidates:
            AppDialog.info(self, self.t("no_healthy_title"), self.t("need_refresh"), self.t("ok"))
            return

        from .workers import BestServerSelectionThread

        thread = BestServerSelectionThread(candidates, self.language, limit=limit)
        self._best_selection_thread = thread
        self._best_selection_result = []
        self._best_selection_error = ""
        self.worker = thread
        self.set_busy(
            True,
            "در حال انتخاب بهترین سرور با تست واقعی…"
            if self.language != "en" else
            "Selecting the best server with real tunnel tests…",
        )
        thread.stage.connect(self._set_stage_text)
        thread.progress.connect(self.update_progress)
        thread.success.connect(lambda rows: setattr(self, "_best_selection_result", list(rows or [])))
        thread.failed.connect(lambda message: setattr(self, "_best_selection_error", str(message)))

        def finalize():
            if self.worker is thread:
                self.worker = None
            self._best_selection_thread = None
            rows = list(self._best_selection_result)
            error = self._best_selection_error
            thread.deleteLater()
            if rows:
                self.store.save_servers(self.servers)
                self.set_busy(False, self.t("checking_connection"))
                self._auto_connect_queue = list(rows[1:])
                self.connect_server(rows[0], automatic=True)
                return
            self.set_busy(False, self.t("connection_failed"))
            self.update_connection_ui()
            AppDialog.error(
                self,
                self.t("connection_error"),
                error or (
                    "هیچ سروری در تست واقعی پاسخ نداد"
                    if self.language != "en" else
                    "No server passed the real tunnel test"
                ),
                self.t("ok"),
            )

        thread.finished.connect(finalize)
        thread.start()

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
