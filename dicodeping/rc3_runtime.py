from __future__ import annotations

import concurrent.futures
import socket
import time

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QPushButton

from . import net as net_module
from . import service as service_module
from .models import DiscoveredConfig
from .protocols import blob_to_config, parse_endpoint
from .rc3_core import median_latency, trusted_latency

_PATCHED = False


def _tcp_samples(ip: str, port: int, attempts: int = 3, timeout: float = 1.4) -> list[int]:
    values: list[int] = []
    for _ in range(max(1, attempts)):
        started = time.perf_counter()
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                values.append(max(1, int(round((time.perf_counter() - started) * 1000))))
        except OSError:
            pass
        time.sleep(0.04)
    return values


def _probe_server(key: str, host: str, port: int):
    addresses = net_module.resolve_all_ipv4(host)[:4]
    choices: list[tuple[int, str]] = []
    for ip in addresses:
        tcp = median_latency(_tcp_samples(ip, port))
        if tcp is not None:
            choices.append((tcp, ip))
    if not choices:
        return net_module.PingResult(key, None, addresses[0] if addresses else "dns")
    trusted = [row for row in choices if service_module.MIN_TRUSTED_AUTO_PING_MS <= row[0] <= service_module.MAX_TRUSTED_AUTO_PING_MS]
    latency, ip = min(trusted or choices, key=lambda row: row[0])
    return net_module.PingResult(key, latency, ip)


def _install_service_patch() -> None:
    original_refresh = service_module.ServerService.refresh_saved

    def refresh(self, *args, **kwargs):
        records = self.store.load_servers()
        port_map = {server.host: int(server.port or 443) for server in records if server.host}
        items = list(dict.fromkeys(server.host for server in records if server.host))
        callback = kwargs.get("ping_progress") or kwargs.get("progress")
        results = []
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(48, len(items) or 1))) as pool:
            futures = {pool.submit(_probe_server, host, host, port_map.get(host, 443)): host for host in items}
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    results.append(net_module.PingResult(futures[future], None, ""))
                done += 1
                if callback:
                    callback(done, len(items))
        result_map = {result.key: result for result in results}
        for server in records:
            result = result_map.get(server.host)
            server.last_checked = service_module.utc_now()
            if result and result.ip:
                server.ip = result.ip
            if result and trusted_latency(result.ping_ms, service_module.MIN_TRUSTED_AUTO_PING_MS):
                server.ping_ms = result.ping_ms
                server.status = "online"
                server.failures = 0
            else:
                server.ping_ms = None
                server.status = "unverified"
                server.failures += 1
        ips = [server.ip for server in records if server.ip and server.ip != "dns"]
        geo = self.geo.resolve_many(ips, callback=kwargs.get("geo_progress") or kwargs.get("progress"))
        for server in records:
            row = geo.get(server.ip, {})
            if row:
                server.country = str(row.get("country") or server.country)
                server.country_code = str(row.get("country_code") or server.country_code).upper()
                server.region = str(row.get("region") or server.region)
                server.city = str(row.get("city") or server.city)
                server.isp = str(row.get("isp") or server.isp)
                server.asn = str(row.get("asn") or server.asn)
                server.geo_provider = str(row.get("geo_provider") or server.geo_provider)
                server.geo_confidence = str(row.get("geo_confidence") or server.geo_confidence)
        records.sort(key=service_module._sort_key)
        self.store.save_servers(records)
        return records

    service_module.ServerService.refresh_saved = refresh


class _SelectedPingThread(QThread):
    done = Signal(object)

    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server

    def run(self):
        result = _probe_server(self.server.id, self.server.host, int(self.server.port or 443))
        self.done.emit(result)


def _install_ui_patch() -> None:
    from .ui import MainWindow

    original_init = MainWindow.__init__
    original_resize = MainWindow.resizeEvent
    original_update = MainWindow.update_connection_ui

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._selected_ping_thread = None
        self.home_primary_button.setText("اتصال" if self.language != "en" else "Connect")
        self.home_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.home_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.home_table.setFocusPolicy(Qt.StrongFocus)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setMinimumSectionSize(72)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.selected_ping_button = QPushButton("پینگ سرور انتخاب‌شده" if self.language != "en" else "Ping selected server")
        self.selected_ping_button.clicked.connect(self._rc3_ping_selected)
        self.server_actions_layout.insertWidget(1, self.selected_ping_button)
        self._rc3_apply_responsive_columns(self.width())

    def ping_selected(self):
        if self.worker or self._selected_ping_thread:
            return
        server = self.selected_server()
        if not server:
            self.switch_page(1)
            return
        self.selected_ping_button.setEnabled(False)
        self.selected_ping_button.setText("در حال پینگ…" if self.language != "en" else "Pinging…")
        thread = _SelectedPingThread(server, self)
        self._selected_ping_thread = thread

        def finished(result):
            if result and result.ping_ms is not None:
                server.ping_ms = result.ping_ms
                server.ip = result.ip or server.ip
                server.status = "online" if trusted_latency(result.ping_ms, service_module.MIN_TRUSTED_AUTO_PING_MS) else "unverified"
                self.store.save_servers(self.servers)
                self.render_servers()
                self.footer_state.setText(f"{server.name}: {result.ping_ms} ms")
            else:
                self.footer_state.setText("پاسخی دریافت نشد" if self.language != "en" else "No response")
            self.selected_ping_button.setText("پینگ سرور انتخاب‌شده" if self.language != "en" else "Ping selected server")
            self.selected_ping_button.setEnabled(True)
            thread.deleteLater()
            self._selected_ping_thread = None

        thread.done.connect(finished)
        thread.start()

    def apply_columns(self, width: int):
        compact = width < 1080
        narrow = width < 930
        self.table.setColumnHidden(2, narrow)
        self.table.setColumnHidden(3, compact)
        self.table.setColumnHidden(5, narrow)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        for row in range(self.table.rowCount()):
            button = self.table.cellWidget(row, 6)
            if button:
                button.setMinimumWidth(84)

    def resize(self, event):
        original_resize(self, event)
        self._rc3_apply_responsive_columns(event.size().width())

    def update(self):
        original_update(self)
        if not self.manager.connected and not self.worker:
            self.home_primary_button.setText("اتصال" if self.language != "en" else "Connect")

    MainWindow.__init__ = init
    MainWindow._rc3_ping_selected = ping_selected
    MainWindow._rc3_apply_responsive_columns = apply_columns
    MainWindow.resizeEvent = resize
    MainWindow.update_connection_ui = update


def install_rc3_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_service_patch()
    _install_ui_patch()
