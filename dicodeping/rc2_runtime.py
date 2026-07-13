from __future__ import annotations

import concurrent.futures
import socket
import threading
import time
import urllib.request
from collections import defaultdict

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QApplication, QAbstractItemView

from . import net as net_module
from . import service as service_module
from .constants import HEALTH_URLS
from .models import DiscoveredConfig
from .protocols import blob_to_config, config_to_blob, parse_endpoint, record_id, set_display_name
from .rc2_core import choose_conservative_latency, extract_display_name, infer_country_hint, is_generated_or_unknown_name

_PATCHED = False
_CTX = threading.local()
_LAST: dict[str, tuple[int | None, str]] = {}


def _tcp_latency(ip: str, ports: list[int], timeout: float = 1.35) -> int | None:
    samples = []
    for port in list(dict.fromkeys(p for p in ports if 0 < p <= 65535))[:4]:
        started = time.perf_counter()
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                samples.append((time.perf_counter() - started) * 1000)
        except OSError:
            pass
    return int(round(min(samples))) if samples else None


def _probe(key: str, host: str, ports: list[int]):
    addresses = net_module.resolve_all_ipv4(host)[:4]
    choices = []
    for ip in addresses:
        icmp, _ = net_module.icmp_ping(host, attempts=2, timeout=1.15, resolved_ip=ip)
        tcp = _tcp_latency(ip, ports or [443, 80])
        latency = choose_conservative_latency((icmp, tcp))
        if latency is not None:
            choices.append((latency, ip))
    trusted = [x for x in choices if service_module.MIN_TRUSTED_AUTO_PING_MS <= x[0] <= service_module.MAX_TRUSTED_AUTO_PING_MS]
    result = min(trusted or choices, key=lambda x: x[0]) if choices else (None, addresses[0] if addresses else "dns")
    _LAST[host] = result
    return net_module.PingResult(key, result[0], result[1])


def _ping_many(items, workers=48, callback=None):
    rows = list(items)
    ports = getattr(_CTX, "ports", {}) or {}
    resolved = {host: net_module.resolve_all_ipv4(host)[:4] for _, host in rows}
    direct_routes = net_module.install_direct_host_routes(
        ip for addresses in resolved.values() for ip in addresses
    )
    results, done = [], 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 64))) as pool:
            futures = {pool.submit(_probe, key, host, ports.get(host, [443, 80])): key for key, host in rows}
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    results.append(net_module.PingResult(futures[future], None, ""))
                done += 1
                if callback:
                    callback(done, len(rows))
    finally:
        net_module.remove_direct_host_routes(direct_routes)
    return results


def _metadata(rows):
    names, raws, ports = {}, {}, defaultdict(list)
    for item in rows:
        raw = item.raw if isinstance(item, DiscoveredConfig) else str(item)
        endpoint = parse_endpoint(raw)
        if not endpoint:
            continue
        sid = record_id(raw)
        raws[sid] = raw
        name = extract_display_name(raw)
        if name:
            names[sid] = name
        if endpoint.port not in ports[endpoint.host]:
            ports[endpoint.host].append(endpoint.port)
    return names, raws, dict(ports)


def _repair(service, records, names, raws):
    missing = [s for s in records if len(str(s.country_code or "")) != 2]
    ips = []
    by_id = {}
    for server in missing:
        values = net_module.resolve_all_ipv4(server.host)[:3]
        if server.ip and server.ip != "dns" and server.ip not in values:
            values.insert(0, server.ip)
        by_id[server.id] = values
        ips.extend(values)
    geo = service.geo.resolve_many(ips) if ips else {}
    for server in records:
        original = names.get(server.id, "")
        if original and is_generated_or_unknown_name(server.name):
            server.name = original
        if is_generated_or_unknown_name(server.name):
            server.name = f"{server.protocol or 'Xray'} • {server.host}:{server.port}"
        raw = raws.get(server.id)
        if raw:
            server.config_blob = config_to_blob(set_display_name(raw, server.name))
        ping, ip = _LAST.get(server.host, (None, ""))
        if ip and ip != "dns":
            server.ip = ip
        if ping is not None and service_module.MIN_TRUSTED_AUTO_PING_MS <= ping <= service_module.MAX_TRUSTED_AUTO_PING_MS:
            server.ping_ms, server.status = ping, "online"
        else:
            server.ping_ms, server.status = None, "unverified"
        if len(str(server.country_code or "")) != 2:
            for candidate in by_id.get(server.id, []):
                row = geo.get(candidate, {})
                code = str(row.get("country_code") or "").upper()
                if len(code) == 2:
                    server.ip = candidate
                    server.country = str(row.get("country") or code)
                    server.country_code = code
                    server.region = str(row.get("region") or "")
                    server.city = str(row.get("city") or "")
                    server.isp = str(row.get("isp") or "")
                    server.asn = str(row.get("asn") or "")
                    server.geo_provider = str(row.get("geo_provider") or "multi-provider")
                    server.geo_confidence = str(row.get("geo_confidence") or "provider")
                    break
        if len(str(server.country_code or "")) != 2:
            code, country = infer_country_hint(server.name)
            if code:
                server.country_code, server.country = code, country
                server.geo_provider, server.geo_confidence = "config-name", "name-hint"
    records.sort(key=service_module._sort_key)
    service.store.save_servers(records)
    return records


def _install_service_patch():
    original_build = service_module.ServerService.build_and_save
    original_refresh = service_module.ServerService.refresh_saved
    original_candidate = service_module._is_auto_candidate
    service_module.MAX_SAVED_SERVERS = max(int(service_module.MAX_SAVED_SERVERS), 320)
    service_module.ping_many = _ping_many

    def build(self, raw_configs, *args, **kwargs):
        rows = list(raw_configs)
        names, raws, ports = _metadata(rows)
        _CTX.ports = ports
        try:
            records = original_build(self, rows, *args, **kwargs)
        finally:
            _CTX.ports = {}
        return _repair(self, records, names, raws)

    def refresh(self, *args, **kwargs):
        existing = self.store.load_servers()
        rows = []
        for server in existing:
            try:
                rows.append(DiscoveredConfig(blob_to_config(server.config_blob), server.source_id, server.source_name, server.source_order))
            except Exception:
                pass
        names, raws, ports = _metadata(rows)
        _CTX.ports = ports
        try:
            records = original_refresh(self, *args, **kwargs)
        finally:
            _CTX.ports = {}
        return _repair(self, records, names, raws)

    def candidate(server):
        return original_candidate(server) and str(server.geo_confidence or "").casefold() != "name-hint"

    service_module.ServerService.build_and_save = build
    service_module.ServerService.refresh_saved = refresh
    service_module._is_auto_candidate = candidate


def _routed_ping(self, timeout=2.2):
    if not self.connected:
        return None
    for url in HEALTH_URLS:
        request = urllib.request.Request(url, headers={"User-Agent": "dicodePing/0.1.3", "Cache-Control": "no-cache"})
        started = time.perf_counter()
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
                response.read(1)
            return max(1, int(round((time.perf_counter() - started) * 1000)))
        except Exception:
            continue
    return None


class _DisconnectThread(QThread):
    done = Signal()
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
    def run(self):
        self.manager.stop()
        self.done.emit()


def _install_ui_patch():
    from .ui import MainWindow, repolish, tinted_icon
    from .workers import ConnectionMonitorThread
    from .xray import XrayManager

    XrayManager.connected_ping = _routed_ping
    original_init = MainWindow.__init__
    original_render = MainWindow._render_home_summary
    original_metrics = MainWindow._connection_metrics_updated
    original_update = MainWindow.update_connection_ui

    def monitor_run(self):
        upload = download = 0
        next_stats = next_ping = 0.0
        while not self.isInterruptionRequested() and self.manager.connected:
            now = time.monotonic()
            payload = {}
            if now >= next_stats:
                upload, download = self.manager.traffic_stats()
                payload.update(upload=upload, download=download)
                next_stats = now + 2.0
            if now >= next_ping:
                payload.update(ping=self.manager.connected_ping(2.2), ping_sampled=True)
                next_ping = now + 5.0
            if payload:
                payload.setdefault("upload", upload)
                payload.setdefault("download", download)
                self.updated.emit(payload)
            self.msleep(250)
    ConnectionMonitorThread.run = monitor_run

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._disconnecting = False
        self._disconnect_thread = None
        self.home_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.home_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.home_table.itemClicked.connect(lambda item: self._rc2_home_select(item.row(), False))
        self.home_table.itemDoubleClicked.connect(lambda item: self._rc2_home_select(item.row(), True))

    def home_select(self, row, connect=False):
        item = self.home_table.item(row, 0)
        sid = item.data(Qt.UserRole) if item else ""
        if not sid:
            return
        self.settings["selected_server_id"] = sid
        self.settings["connection_mode"] = "manual"
        if hasattr(self, "connection_mode_combo"):
            index = self.connection_mode_combo.findData("manual")
            if index >= 0:
                self.connection_mode_combo.setCurrentIndex(index)
        self._restoring_server_selection = True
        try:
            for table_row in range(self.table.rowCount()):
                name_item = self.table.item(table_row, 1)
                if name_item and name_item.data(Qt.UserRole) == sid:
                    self.table.selectRow(table_row)
                    break
        finally:
            self._restoring_server_selection = False
        self.store.save_settings(self.settings)
        if connect:
            self.connect_by_id(sid)
        else:
            self._render_home_summary()

    def render(self):
        original_render(self)
        top = [s for s in self.servers if s.status == "online" and s.ping_ms is not None]
        top.sort(key=lambda s: s.ping_ms or 999999)
        selected = str(self.settings.get("selected_server_id", ""))
        for row, server in enumerate(top[:4]):
            item = self.home_table.item(row, 0)
            if item:
                item.setData(Qt.UserRole, server.id)
                item.setToolTip("برای انتخاب کلیک و برای اتصال دوبار کلیک کنید" if self.language != "en" else "Click to select, double-click to connect")
            if server.id == selected:
                self.home_table.selectRow(row)

    def metrics(self, payload):
        original_metrics(self, payload)
        if isinstance(payload, dict) and payload.get("ping_sampled") and not isinstance(payload.get("ping"), int):
            self.live_ping_value.setText("—")

    def update(self):
        if getattr(self, "_disconnecting", False):
            text = "در حال قطع اتصال…" if self.language != "en" else "Disconnecting…"
            self._set_status_visual("busy", text)
            self.home_hero_title.setText(text)
            self.home_hero_detail.setText("در حال پاک‌سازی مسیر TUN و DNS" if self.language != "en" else "Cleaning TUN routes and DNS")
            self.home_primary_button.setText(text)
            self.home_primary_button.setIcon(tinted_icon("refresh.svg"))
            self.home_primary_button.setProperty("kind", "danger")
            self.home_primary_button.setEnabled(False)
            repolish(self.home_primary_button)
            return
        original_update(self)

    def disconnect(self, *, show_message=True):
        if self._disconnecting:
            return
        self._stop_connect_animation()
        self._stop_connection_monitor()
        self._disconnecting = True
        self.update_connection_ui()
        QApplication.processEvents()
        thread = _DisconnectThread(self.manager, self)
        self._disconnect_thread = thread
        def finish():
            self._disconnecting = False
            self.connected_id = ""
            self.live_metrics_card.setVisible(False)
            self.live_download_value.setText("0 B")
            self.live_upload_value.setText("0 B")
            self.live_ping_value.setText("—")
            self.update_connection_ui()
            self.render_servers()
            if show_message:
                self.home_hero_detail.setText(self.t("disconnected"))
            thread.deleteLater()
            self._disconnect_thread = None
        thread.done.connect(finish)
        thread.start()

    MainWindow.__init__ = init
    MainWindow._rc2_home_select = home_select
    MainWindow._render_home_summary = render
    MainWindow._connection_metrics_updated = metrics
    MainWindow.update_connection_ui = update
    MainWindow.disconnect = disconnect


def install_rc2_patches():
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_service_patch()
    _install_ui_patch()
