from __future__ import annotations

import sys
import time
from typing import Any

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from dicodeping.constants import APP_ID, APP_NAME, ASSET_DIR, RUNTIME_DIR, VERSION
from dicodeping.diagnostics import configure_logging, get_logger
from dicodeping.discovery import discover_config_entries
from dicodeping.service import ServerService
from dicodeping.sources import normalize_sources, serialize_sources
from dicodeping.storage import JsonStore
from dicodeping.ui import MainWindow
from dicodeping.windows_integration import apply_native_window_icon, set_process_app_user_model_id
from dicodeping.xray import cleanup_stale_owned_process, is_admin, is_windows, relaunch_as_admin

LOGGER = get_logger("startup")
SERVER_REFRESH_INTERVAL_SECONDS = 2 * 24 * 60 * 60


class StartupSplash(QWidget):
    def __init__(self, language: str = "fa") -> None:
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(430, 245)
        rtl = language != "en"
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background:#101722; border:1px solid #273448; border-radius:22px; }
            QLabel { border:none; color:#F4F7FB; background:transparent; }
            QLabel#muted { color:#93A0B2; }
            QProgressBar { border:none; background:#1B2637; border-radius:3px; height:6px; }
            QProgressBar::chunk { background:#6D8EFF; border-radius:3px; }
        """)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(ASSET_DIR / "app.png")).pixmap(52, 52))
        head.addWidget(logo)
        titles = QVBoxLayout()
        title = QLabel("dicodePing")
        title.setStyleSheet("font-size:24px;font-weight:700;color:#F8FAFF")
        subtitle = QLabel("اتصال ساده و سریع" if rtl else "Simple, fast connection")
        subtitle.setObjectName("muted")
        subtitle.setStyleSheet("font-size:12px;color:#93A0B2")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        layout.addLayout(head)
        layout.addStretch()
        self.status = QLabel("در حال آماده سازی برنامه..." if rtl else "Preparing application...")
        self.status.setObjectName("muted")
        self.status.setStyleSheet("font-size:12px;color:#93A0B2")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setValue(4)
        layout.addWidget(self.progress)

    def set_stage(self, value: int, fa: str, en: str, language: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, value)))
        self.status.setText(en if language == "en" else fa)

    def set_indeterminate(self, fa: str, en: str, language: str) -> None:
        self.progress.setRange(0, 0)
        self.status.setText(en if language == "en" else fa)


class StartupPrepareThread(QThread):
    stage = Signal(int, str, str)
    ready = Signal(object, object, str)

    def __init__(self, language: str) -> None:
        super().__init__()
        self.language = language

    def run(self) -> None:
        store = JsonStore()
        service = ServerService(store)
        settings = store.load_settings()
        cached = store.load_servers()
        startup_error = ""
        try:
            self.stage.emit(8, "در حال بارگذاری تنظیمات...", "Loading settings...")
            sources = normalize_sources(settings, self.language)
            settings["sources"] = serialize_sources(sources)
            settings.pop("custom_subscriptions", None)

            last_refresh = float(settings.get("last_server_refresh_at", 0) or 0)
            due = not cached or (time.time() - last_refresh) >= SERVER_REFRESH_INTERVAL_SECONDS
            if due:
                enabled = [source for source in sources if source.enabled]
                self.stage.emit(15, "در حال دریافت سرورها...", "Downloading servers...")
                entries = discover_config_entries(
                    enabled,
                    stage=lambda text: self.stage.emit(22, text, text),
                    progress=lambda current, total: self.stage.emit(
                        15 + int(22 * max(0, current) / max(1, total)),
                        "در حال دریافت سرورها...",
                        "Downloading servers...",
                    ),
                    language=self.language,
                )
                servers = service.build_and_save(
                    entries,
                    stage=lambda text: self.stage.emit(48, text, text),
                    language=self.language,
                    ping_progress=lambda current, total: self.stage.emit(
                        40 + int(30 * max(0, current) / max(1, total)),
                        "در حال سنجش پاسخ سرورها...",
                        "Testing server response...",
                    ),
                    geo_progress=lambda current, total: self.stage.emit(
                        70 + int(22 * max(0, current) / max(1, total)),
                        "در حال تشخیص موقعیت سرورها...",
                        "Resolving server locations...",
                    ),
                )
                cached = servers
                settings["last_server_refresh_at"] = int(time.time())
                LOGGER.info("Startup refresh completed: %d servers", len(cached))
            else:
                self.stage.emit(82, "در حال استفاده از اطلاعات ذخیره شده...", "Using cached server data...")
                LOGGER.info("Startup cache is fresh: %d servers", len(cached))

            store.save_settings(settings)
            self.stage.emit(96, "در حال آماده سازی رابط...", "Preparing interface...")
        except Exception as exc:
            LOGGER.exception("Startup preparation failed")
            startup_error = str(exc)
            cached = cached or store.load_servers()
        self.ready.emit(cached, settings, startup_error)


_SINGLE_INSTANCE_HANDLE = None


def acquire_single_instance() -> bool:
    global _SINGLE_INSTANCE_HANDLE
    if not is_windows():
        try:
            import fcntl

            lock_path = RUNTIME_DIR / "instance.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            _SINGLE_INSTANCE_HANDLE = lock_path.open("a+")
            fcntl.flock(_SINGLE_INSTANCE_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, ImportError):
            return False
    try:
        import ctypes

        _SINGLE_INSTANCE_HANDLE = ctypes.windll.kernel32.CreateMutexW(
            None,
            False,
            "Global\\dicodePing.SingleInstance",
        )
        return bool(_SINGLE_INSTANCE_HANDLE) and ctypes.windll.kernel32.GetLastError() != 183
    except Exception:
        return True


def set_app_id() -> None:
    if is_windows() and not set_process_app_user_model_id(APP_ID):
        LOGGER.warning("Windows AppUserModelID could not be applied")


def load_application_icon() -> QIcon:
    # ICO is used first on Windows so Qt and the embedded executable resource
    # resolve to the same artwork. PNG remains a portable fallback.
    candidates = (ASSET_DIR / "app.ico", ASSET_DIR / "app.png") if is_windows() else (
        ASSET_DIR / "app.png",
        ASSET_DIR / "app.ico",
    )
    for candidate in candidates:
        icon = QIcon(str(candidate))
        if not icon.isNull():
            return icon
    return QIcon()


def choose_persian_font() -> QFont:
    available = set(QFontDatabase.families())
    for family in ("Vazirmatn", "Vazir", "Vazir FD", "Tahoma", "Segoe UI"):
        if family in available:
            return QFont(family, 10)
    return QFont("Sans Serif", 10)


def main() -> int:
    settings = JsonStore().load_settings()
    configure_logging(bool(settings.get("diagnostic_logging", False)), str(settings.get("log_level", "INFO")))
    LOGGER.info("Application startup requested")
    if not is_admin():
        if relaunch_as_admin():
            return 0
        if is_windows():
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(
                    0,
                    "برای ساخت رابط TUN باید برنامه با دسترسی Administrator اجرا شود.",
                    "دسترسی مدیر",
                    0x10,
                )
            except Exception:
                print("Administrator access is required.")
        else:
            print("Root access is required to create the Linux TUN interface. Run with sudo or install PolicyKit.")
        return 1

    if not acquire_single_instance():
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, "dicodePing هم اکنون در حال اجرا است.", "dicodePing", 0x40)
        except Exception:
            pass
        return 0

    cleanup_stale_owned_process()
    set_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("Dicode")
    app.setOrganizationDomain("dicode.ir")
    application_icon = load_application_icon()
    if not application_icon.isNull():
        app.setWindowIcon(application_icon)
    app.setFont(choose_persian_font())
    language = "en" if settings.get("language") == "en" else "fa"
    app.setLayoutDirection(Qt.LeftToRight if language == "en" else Qt.RightToLeft)

    splash = StartupSplash(language)
    if not application_icon.isNull():
        splash.setWindowIcon(application_icon)
    splash.show()
    screen = app.primaryScreen()
    if screen:
        splash.move(screen.availableGeometry().center() - splash.rect().center())

    state: dict[str, Any] = {"window": None, "worker": None}
    worker = StartupPrepareThread(language)
    state["worker"] = worker
    worker.stage.connect(lambda value, fa, en: splash.set_stage(value, fa, en, language))

    def prepared(servers: object, prepared_settings: object, startup_error: str) -> None:
        rows = list(servers) if isinstance(servers, list) else []
        loaded_settings = dict(prepared_settings) if isinstance(prepared_settings, dict) else settings
        window = MainWindow(
            preloaded_servers=rows,
            preloaded_settings=loaded_settings,
            startup_prepared=True,
            startup_error=startup_error,
        )
        state["window"] = window
        splash.set_stage(100, "آماده", "Ready", language)
        window.show()
        if is_windows():
            # Force the native HWND icon after creation. This complements the
            # application/window QIcon and fixes generic taskbar icons for the
            # frameless elevated PyInstaller build on Windows 10/11.
            QTimer.singleShot(0, lambda: apply_native_window_icon(window, ASSET_DIR / "app.ico"))
        splash.close()
        worker.quit()
        worker.deleteLater()
        state["worker"] = None

    worker.ready.connect(prepared)
    worker.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
