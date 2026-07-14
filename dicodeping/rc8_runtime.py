from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QBoxLayout, QHeaderView, QSizePolicy

from .rc8_core import primary_action_key, responsive_server_columns

_PATCHED = False


def _install_ui_patch() -> None:
    from .ui import MainWindow

    original_init = MainWindow.__init__
    original_resize = MainWindow.resizeEvent
    original_update = MainWindow.update_connection_ui

    def apply_responsive(self) -> None:
        if not hasattr(self, "table"):
            return
        viewport_width = max(0, self.table.viewport().width())
        for column, visible in responsive_server_columns(viewport_width).items():
            self.table.setColumnHidden(column, not visible)

        # rc3 changed this back to ResizeToContents on every resize, which made
        # the action button collapse. rc8 owns this column after the full chain.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 116)
        for row in range(self.table.rowCount()):
            button = self.table.cellWidget(row, 6)
            if button:
                button.setMinimumWidth(104)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        content_width = max(viewport_width, self.pages.width() if hasattr(self, "pages") else viewport_width)
        narrow_actions = content_width < 720
        horizontal = QBoxLayout.RightToLeft if self.is_rtl else QBoxLayout.LeftToRight
        self.server_actions_layout.setDirection(QBoxLayout.TopToBottom if narrow_actions else horizontal)
        for index in range(self.server_actions_layout.count()):
            widget = self.server_actions_layout.itemAt(index).widget()
            if widget:
                widget.setSizePolicy(QSizePolicy.Expanding if narrow_actions else QSizePolicy.Preferred, QSizePolicy.Fixed)

        toolbar = getattr(self, "server_toolbar_layout", None)
        if toolbar:
            toolbar.setDirection(QBoxLayout.TopToBottom if content_width < 520 else horizontal)
        compact_settings = content_width < 620
        for layout in getattr(self, "settings_advanced_rows", []):
            layout.setDirection(QBoxLayout.TopToBottom if compact_settings else horizontal)

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._rc8_apply_responsive()
        QTimer.singleShot(0, self._rc8_apply_responsive)

    def resize(self, event):
        original_resize(self, event)
        self._rc8_apply_responsive()
        QTimer.singleShot(0, self._rc8_apply_responsive)

    def update(self):
        original_update(self)
        key = primary_action_key(
            connected=self.manager.connected,
            busy=bool(self.worker),
            has_servers=bool(self.servers),
            manual=self.settings.get("connection_mode", "auto") == "manual",
            has_selected=self.selected_server() is not None,
            has_best=self.service.best_server(self.servers) is not None,
        )
        if key == "connect":
            self.home_primary_button.setText(self.t("connect"))
        elif key not in {"busy", "disconnect"}:
            self.home_primary_button.setText(self.t(key))

    MainWindow.__init__ = init
    MainWindow.resizeEvent = resize
    MainWindow.update_connection_ui = update
    MainWindow._rc8_apply_responsive = apply_responsive


def install_rc8_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _install_ui_patch()
