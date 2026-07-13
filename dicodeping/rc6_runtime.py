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

    def close(self, event):
        worker = getattr(self, "worker", None)
        if worker and worker.isRunning():
            worker.requestInterruption()
            # Give cooperative progress callbacks a short chance to unwind. If a
            # socket call is still active, keep the window alive and close as soon
            # as the worker exits instead of destroying a running QThread.
            if not worker.wait(1800):
                if not self._rc6_close_pending:
                    self._rc6_close_pending = True
                    worker.finished.connect(self._rc6_finish_pending_close)
                event.ignore()
                return
        self._rc6_close_pending = False
        original_close(self, event)

    def finish_pending_close(self):
        if not self._rc6_close_pending:
            return
        self._rc6_close_pending = False
        QTimer.singleShot(0, self.close)

    MainWindow.__init__ = init
    MainWindow.closeEvent = close
    MainWindow._rc6_finish_pending_close = finish_pending_close


def install_rc6_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_ui_patch()
