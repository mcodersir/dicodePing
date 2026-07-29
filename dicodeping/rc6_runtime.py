from __future__ import annotations

from PySide6.QtCore import QTimer

_PATCHED = False


def _install_ui_patch() -> None:
    from .ui import MainWindow

    original_init = MainWindow.__init__
    original_close = MainWindow.closeEvent

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._rc6_close_pending = False
        self._rc6_close_timer_armed = False
        self._retired_threads = []

    def active_threads(self):
        rows = []
        for name in ("worker", "scanner_thread", "connection_monitor", "_disconnect_thread", "_sharing_thread"):
            thread = getattr(self, name, None)
            if thread is not None and hasattr(thread, "isRunning") and thread.isRunning():
                rows.append(thread)
        rows.extend(
            thread for thread in getattr(self, "_retired_threads", [])
            if hasattr(thread, "isRunning") and thread.isRunning()
        )
        return list(dict.fromkeys(rows))

    def schedule_close_retry(self):
        if self._rc6_close_timer_armed:
            return
        self._rc6_close_timer_armed = True

        def retry():
            self._rc6_close_timer_armed = False
            if self._rc6_close_pending:
                self.close()

        QTimer.singleShot(140, retry)

    def close(self, event):
        worker = getattr(self, "worker", None)
        if worker and worker.isRunning():
            if not getattr(worker, "_rc6_close_hooked", False):
                worker._rc6_close_hooked = True
                worker.finished.connect(lambda: schedule_close_retry(self))
            worker.requestInterruption()
        scanner = getattr(self, "scanner_thread", None)
        if scanner and scanner.isRunning():
            if not getattr(scanner, "_rc6_close_hooked", False):
                scanner._rc6_close_hooked = True
                scanner.finished.connect(lambda: schedule_close_retry(self))
            scanner.requestStop()
        monitor = getattr(self, "connection_monitor", None)
        if monitor and monitor.isRunning():
            if not getattr(monitor, "_rc6_close_hooked", False):
                monitor._rc6_close_hooked = True
                monitor.finished.connect(lambda: schedule_close_retry(self))
            monitor.requestInterruption()

        # Use the normal asynchronous teardown path. It owns the native core and
        # must finish before Qt destroys any manager or worker objects.
        if getattr(self.manager, "connected", False) and not getattr(self, "_disconnecting", False):
            self.disconnect(show_message=False)

        if active_threads(self) or getattr(self, "_disconnecting", False):
            self._rc6_close_pending = True
            event.ignore()
            schedule_close_retry(self)
            return

        self._rc6_close_pending = False
        original_close(self, event)

    MainWindow.__init__ = init
    MainWindow.closeEvent = close
    MainWindow._rc6_active_threads = active_threads
    MainWindow._rc6_schedule_close_retry = schedule_close_retry


def install_rc6_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_ui_patch()
