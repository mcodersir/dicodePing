"""dicodePing Version 3 desktop entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from dicodeping.client import CoreHostClient
from dicodeping.diagnostics import configure_logging, get_logger
from dicodeping.font_loader import register_vazirmatn
from dicodeping.service import AppService
from dicodeping.storage import JsonStore
from dicodeping.ui import MainWindow

LOGGER = get_logger("app")


def main() -> int:
    configure_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("dicodePing")
    app.setOrganizationName("dicode")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        register_vazirmatn()
    except Exception:
        LOGGER.debug("Bundled font is unavailable", exc_info=True)

    store = JsonStore()
    runtime = CoreHostClient()
    service = AppService(store, runtime)
    window = MainWindow(service, store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
