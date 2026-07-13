from __future__ import annotations

from PySide6.QtCore import QTimer

from .rc5_core import auto_retry_ids, connection_lost_message

_PATCHED = False


def _install_ui_patch() -> None:
    from .ui import AppDialog, MainWindow

    original_init = MainWindow.__init__
    original_connect_server = MainWindow.connect_server
    original_connect_finished = MainWindow.connect_finished
    original_sync = MainWindow._sync_action_states
    original_start_scan = MainWindow.start_scan
    original_start_refresh = MainWindow.start_refresh
    original_clear_servers = MainWindow.clear_servers
    original_start_monitor = MainWindow._start_connection_monitor
    original_close = MainWindow.closeEvent

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._rc5_auto_active = False
        self._rc5_auto_queue = []
        self._rc5_auto_errors = []
        self._rc5_attempting_id = ""

    def cancel_auto(self):
        self._rc5_auto_active = False
        self._rc5_auto_queue = []
        self._rc5_auto_errors = []
        self._rc5_attempting_id = ""

    def try_next_auto(self):
        if not self._rc5_auto_active or self.manager.connected:
            return
        if self.worker:
            QTimer.singleShot(120, self._rc5_try_next_auto)
            return
        server = None
        while self._rc5_auto_queue and server is None:
            server_id = self._rc5_auto_queue.pop(0)
            server = next((item for item in self.servers if item.id == server_id), None)
        if server is None:
            errors = list(self._rc5_auto_errors)
            self._rc5_cancel_auto()
            detail = errors[-1] if errors else (
                "هیچ سرور قابل اتصالی باقی نماند" if self.language != "en" else "No connectable server remained"
            )
            AppDialog.error(self, self.t("connection_error"), detail, self.t("ok"))
            return
        self._rc5_attempting_id = server.id
        original_connect_server(self, server)

    def connect_best(self):
        if self.worker or self.manager.connected:
            return
        candidates = self.service.auto_candidates(self.servers)
        queue = auto_retry_ids(candidates, limit=5)
        if not queue:
            AppDialog.info(self, self.t("no_healthy_title"), self.t("need_refresh"), self.t("ok"))
            return
        self._rc5_auto_active = True
        self._rc5_auto_queue = queue
        self._rc5_auto_errors = []
        self._rc5_attempting_id = ""
        self._rc5_try_next_auto()

    def connect_failed(self, message):
        server_id = self._rc5_attempting_id
        if server_id:
            for server in self.servers:
                if server.id == server_id:
                    server.status = "unverified"
                    server.ping_ms = None
                    server.failures += 1
                    break
            self.service.mark_probe_failed(server_id)
        self._stop_connect_animation()
        self._stop_connection_monitor()
        self.manager.stop()
        self.connected_id = ""
        self.live_metrics_card.setVisible(False)
        self.set_busy(False, self.t("connection_failed"))
        self.update_connection_ui()
        self.render_servers()
        if self._rc5_auto_active and self._rc5_auto_queue:
            self._rc5_auto_errors.append(str(message).splitlines()[0])
            QTimer.singleShot(180, self._rc5_try_next_auto)
            return
        self._rc5_cancel_auto()
        AppDialog.error(self, self.t("connection_error"), str(message), self.t("ok"))

    def connect_finished(self, server):
        self._rc5_cancel_auto()
        original_connect_finished(self, server)

    def connect_server(self, server):
        if not self._rc5_auto_active:
            self._rc5_attempting_id = server.id
        original_connect_server(self, server)

    def set_manual_mode(self, server_id):
        self._rc5_cancel_auto()
        self.settings["selected_server_id"] = server_id
        self.settings["connection_mode"] = "manual"
        if hasattr(self, "connection_mode_combo"):
            index = self.connection_mode_combo.findData("manual")
            if index >= 0 and self.connection_mode_combo.currentIndex() != index:
                self.connection_mode_combo.setCurrentIndex(index)
        self.store.save_settings(self.settings)

    def connect_by_id(self, server_id):
        server = next((item for item in self.servers if item.id == server_id), None)
        if not server:
            return
        self._rc5_set_manual_mode(server.id)
        connect_server(self, server)

    def connect_selected(self):
        server = self.selected_server()
        if server:
            self._rc5_set_manual_mode(server.id)
            connect_server(self, server)

    def sync(self, busy=None):
        original_sync(self, busy)
        connected = self.manager.connected
        if connected:
            for button in (self.home_scan_button, self.server_scan_button, self.empty_scan_button,
                           self.home_refresh_button, self.server_refresh_button, self.server_best_button):
                button.setEnabled(False)
        if hasattr(self, "selected_ping_button"):
            self.selected_ping_button.setEnabled(not connected and not bool(self.worker) and self._selected_ping_thread is None)

    def start_scan(self):
        if self.manager.connected:
            return
        original_start_scan(self)

    def start_refresh(self, auto=False):
        if self.manager.connected:
            return
        original_start_refresh(self, auto)

    def ping_selected(self):
        if self.manager.connected:
            return
        return self._rc3_ping_selected_original()

    def clear_servers(self):
        if self.manager.connected:
            return
        original_clear_servers(self)

    def start_monitor(self):
        original_start_monitor(self)
        if self.connection_monitor:
            self.connection_monitor.connection_lost.connect(self._rc5_connection_lost)

    def connection_lost(self):
        if getattr(self, "_disconnecting", False) or getattr(self, "_is_closing", False):
            return
        server = next((item for item in self.servers if item.id == self.connected_id), None)
        server_id = self.connected_id
        self._stop_connection_monitor()
        self.manager.stop()
        self.connected_id = ""
        if server_id:
            if server:
                server.status = "unverified"
                server.ping_ms = None
                server.failures += 1
            self.service.mark_probe_failed(server_id)
        self.live_metrics_card.setVisible(False)
        self.live_download_value.setText("0 B")
        self.live_upload_value.setText("0 B")
        self.live_ping_value.setText("—")
        self.update_connection_ui()
        self.render_servers()
        self.home_hero_detail.setText(connection_lost_message(self.language, server.name if server else ""))

    def close(self, event):
        if self.worker:
            self.worker.requestInterruption()
        selected_ping = getattr(self, "_selected_ping_thread", None)
        if selected_ping and selected_ping.isRunning():
            selected_ping.requestInterruption()
            selected_ping.wait(4500)
        self._rc5_cancel_auto()
        original_close(self, event)

    MainWindow.__init__ = init
    MainWindow._rc5_cancel_auto = cancel_auto
    MainWindow._rc5_try_next_auto = try_next_auto
    MainWindow._rc5_set_manual_mode = set_manual_mode
    MainWindow.connect_best = connect_best
    MainWindow.connect_failed = connect_failed
    MainWindow.connect_finished = connect_finished
    MainWindow.connect_server = connect_server
    MainWindow.connect_by_id = connect_by_id
    MainWindow.connect_selected = connect_selected
    MainWindow._sync_action_states = sync
    MainWindow.start_scan = start_scan
    MainWindow.start_refresh = start_refresh
    MainWindow.clear_servers = clear_servers
    MainWindow._start_connection_monitor = start_monitor
    MainWindow._rc5_connection_lost = connection_lost
    MainWindow.closeEvent = close
    if hasattr(MainWindow, "_rc3_ping_selected"):
        MainWindow._rc3_ping_selected_original = MainWindow._rc3_ping_selected
        MainWindow._rc3_ping_selected = ping_selected


def install_rc5_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_ui_patch()
