"""Final v1.8.0 RC2 presentation patch.

This layer deliberately owns only geometry and motion.  Network, discovery,
probe and connection state machines remain untouched.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QBoxLayout, QHeaderView, QSizePolicy

from .design_system import WindowClass, desktop_server_columns, window_class

_PATCHED = False


def install_rc9_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    from .ui import MainWindow

    original_init = MainWindow.__init__
    original_resize = MainWindow.resizeEvent

    def apply_layout(self) -> None:
        mode = window_class(self.width())
        horizontal = QBoxLayout.RightToLeft if self.is_rtl else QBoxLayout.LeftToRight
        if hasattr(self, "server_header_layout"):
            self.server_header_layout.setDirection(
                QBoxLayout.LeftToRight if mode is WindowClass.EXPANDED else QBoxLayout.TopToBottom
            )
            self.server_actions_layout.setDirection(
                QBoxLayout.TopToBottom if self.width() < 760 else horizontal
            )
            for index in range(self.server_actions_layout.count()):
                widget = self.server_actions_layout.itemAt(index).widget()
                if widget:
                    widget.setSizePolicy(
                        QSizePolicy.Expanding if self.width() < 760 else QSizePolicy.Preferred,
                        QSizePolicy.Fixed,
                    )
        if hasattr(self, "table"):
            for column, visible in desktop_server_columns(self.width()).items():
                self.table.setColumnHidden(column, not visible)
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(1, QHeaderView.Stretch)
            header.setSectionResizeMode(7, QHeaderView.Fixed)
            self.table.setColumnWidth(7, 124)
            if not self._busy_list_task:
                rows = self.server_card_list.count()
                self.server_stack.setCurrentIndex(
                    3 if rows and mode is WindowClass.COMPACT else (0 if rows else 1)
                )
        if hasattr(self, "settings_category_list"):
            self.settings_category_list.setVisible(mode is not WindowClass.COMPACT)
            self.settings_category_combo.setVisible(mode is WindowClass.COMPACT)
            self.settings_body_layout.setDirection(
                QBoxLayout.TopToBottom if mode is WindowClass.COMPACT else horizontal
            )
        if hasattr(self, "scanner_stepper_layout"):
            self.scanner_stepper_layout.setDirection(
                QBoxLayout.TopToBottom if mode is WindowClass.COMPACT else horizontal
            )

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._rc2_apply_layout()
        if self.settings.get("reduced_motion"):
            self._show_animation.setDuration(0)
        QTimer.singleShot(0, self._rc2_apply_layout)

    def resize(self, event):
        original_resize(self, event)
        self._rc2_apply_layout()

    MainWindow.__init__ = init
    MainWindow.resizeEvent = resize
    MainWindow._rc2_apply_layout = apply_layout
