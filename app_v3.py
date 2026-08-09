"""dicodePing Version 3 — entry point.

This is the Version 3 entry point that wires together the v2rayN-based
networking stack with the modern PySide6 Qt UI.

Version 3 replaces the legacy Python networking wrapper with a proper
v2rayN integration layer while preserving the existing subscription
source and project-specific business logic.
"""
from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

# Ensure the project root is on sys.path for imports
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import v2rayN integration layer
from dicodeping.v2rayN.integration import (
    ConnectionManager,
    ServerService,
    XrayManager,
    resolve_ipv4,
    is_url_reachable,
    lookup_geo,
)
from dicodeping.v2rayN.integration.constants import (
    APP_ID,
    APP_NAME,
    VERSION,
    RELEASE_VERSION,
    DEFAULT_SUBSCRIPTION_URL,
    DATA_DIR,
    ASSET_DIR,
    TUN_NAME,
)
from dicodeping.v2rayN.integration.ui_v3 import (
    MainWindowV3,
    ThemeManager,
    theme_manager,
    tokens,
)

# Import business logic (preserved from v2)
from dicodeping.constants import APP_ID as DIC_ID, APP_NAME as DIC_NAME
from dicodeping.diagnostics import configure_logging, get_logger
from dicodeping.storage import JsonStore

LOGGER = get_logger("app_v3")
SERVER_REFRESH_INTERVAL_SECONDS = 2 * 24 * 60 * 60


def check_connectivity() -> bool:
    """Check if the network is reachable."""
    from dicodeping.v2rayN.integration.constants import HEALTH_URLS
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(is_url_reachable, url, 5.0) for url in HEALTH_URLS]
        for future in concurrent.futures.as_completed(futures, timeout=8.0):
            try:
                if future.result():
                    return True
            except Exception:
                pass
    return False


def main() -> int:
    """Run the Version 3 application."""
    # Configure logging
    configure_logging()
    LOGGER.info("Starting dicodePing v%s", VERSION)

    # Ensure data directories exist
    for path in (DATA_DIR, DATA_DIR / "runtime", DATA_DIR / "cache", DATA_DIR / "core"):
        path.mkdir(parents=True, exist_ok=True)

    # Initialize store
    store = JsonStore()
    service = ServerService(store)
    service = ServerService(store)

    # Initialize connection manager
    connection_manager = ConnectionManager()

    # Create Qt application
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    theme_manager.apply_palette(app)

    # Register Vazirmatn font
    try:
        from dicodeping.font_loader import register_vazirmatn
        register_vazirmatn()
    except Exception:
        LOGGER.debug("Font registration skipped", exc_info=True)

    # Create main window
    window = MainWindowV3()

    # Auto-fetch subscription servers if list is empty
    if not service.saved_records():
        LOGGER.info("No saved servers found. Triggering background subscription auto-fetch...")
        import threading
        def _bg_fetch():
            try:
                service.build_and_save(DEFAULT_SUBSCRIPTION_URL)
                LOGGER.info("Subscription auto-fetched successfully.")
            except Exception as exc:
                LOGGER.warning("Subscription auto-fetch failed: %s", exc)
        threading.Thread(target=_bg_fetch, daemon=True).start()

    # Wire up the connection manager to the UI
    def on_connect():
        """Handle connect button click."""
        best = service.best_server()
        if not best:
            LOGGER.warning("No suitable server found for connection")
            window.status_bar.set_message("هیچ سروری یافت نشد")
            return
        try:
            window.status_bar.set_state("connecting")
            # Connect using the v2rayN stack
            raw_config = best.config_blob
            connection_manager.start(raw_config, language="fa")
            window.status_bar.set_state("connected")
            service.update_connected(best.id)
        except Exception as exc:
            LOGGER.error("Connection failed: %s", exc)
            window.status_bar.set_state("disconnected")
            window.status_bar.set_message(str(exc))

    def on_disconnect():
        """Handle disconnect button click."""
        connection_manager.stop()
        window.status_bar.set_state("disconnected")

    # Connect the connect button
    if hasattr(window, "dashboard_view") and hasattr(window.dashboard_view, "_connect_btn"):
        window.dashboard_view._connect_btn.clicked.connect(on_connect)

    # Show window
    window.show()

    # Start event loop
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
