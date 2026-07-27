"""RC9 cross-platform interaction and bundled-core presentation patches."""
from __future__ import annotations

_PATCHED = False


def install_rc11_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    from .ui import MainWindow

    original_init = MainWindow.__init__
    original_sync = MainWindow._sync_core_mode_ui

    def keep_management_available(self) -> None:
        original_sync(self)
        # Server management and the scanner are management surfaces and must
        # stay reachable even when Aether or WARP is the selected connection core.
        for index in (1, 2):
            if index < len(self.sidebar.buttons):
                self.sidebar.buttons[index].setEnabled(True)
                self.sidebar.buttons[index].setToolTip("")
        for name in ("home_scan_button", "home_refresh_button", "home_open_servers_button"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setVisible(True)
                widget.setEnabled(True)

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Consistent click affordance across Windows, Linux and macOS.
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.PointingHandCursor)
        keep_management_available(self)

    MainWindow.__init__ = patched_init
    MainWindow._sync_core_mode_ui = keep_management_available
