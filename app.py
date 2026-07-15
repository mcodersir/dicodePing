from __future__ import annotations

import sys
import os
import traceback
from typing import Any
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from dicodeping.constants import APP_ID, APP_NAME, ASSET_DIR, RELEASE_VERSION, RUNTIME_DIR, VERSION
from dicodeping.diagnostics import configure_logging, get_logger
from dicodeping.rc9_core import StartupGate, server_refresh_due, startup_rows
from dicodeping.sources import normalize_sources, serialize_sources
from dicodeping.storage import JsonStore
from dicodeping.ui import MainWindow
from dicodeping.updates import check_source_updates, find_application_update
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
    ready = Signal(object, object, str, bool)

    def __init__(self, language: str) -> None:
        super().__init__()
        self.language = language

    def run(self) -> None:
        store = JsonStore()
        settings: dict[str, Any] = {}
        cached: list[Any] = []
        startup_error = ""
        refresh_due = True
        try:
            self.stage.emit(8, "در حال بارگذاری تنظیمات...", "Loading settings...")
            settings = store.load_settings()
            cached = store.load_servers()
            sources = normalize_sources(settings, self.language)
            settings["sources"] = serialize_sources(sources)
            settings.pop("custom_subscriptions", None)
            refresh_due = server_refresh_due(
                len(cached),
                settings.get("last_server_refresh_at", 0),
                interval_seconds=SERVER_REFRESH_INTERVAL_SECONDS,
            )
            store.save_settings(settings)
            self.stage.emit(82, "در حال بارگذاری اطلاعات ذخیره شده...", "Loading cached server data...")
            self.stage.emit(96, "در حال آماده سازی رابط...", "Preparing interface...")
        except Exception as exc:
            LOGGER.exception("Startup preparation failed")
            startup_error = str(exc)
            try:
                settings = settings or store.load_settings()
                cached = cached or store.load_servers()
            except Exception:
                LOGGER.exception("Startup cache recovery failed")
        self.ready.emit(cached, settings, startup_error, refresh_due)


class UpdateCheckThread(QThread):
    """Network-only update check, intentionally outside the startup gate."""
    ready = Signal(object, object)

    def __init__(self, settings: dict[str, Any], language: str) -> None:
        super().__init__()
        self.settings = dict(settings)
        self.language = language

    def run(self) -> None:
        try:
            # An app update is time-sensitive at startup.  Do not make it wait
            # for every subscription mirror before presenting the prompt.
            platform = "windows" if is_windows() else "linux"
            release = find_application_update(RELEASE_VERSION, platform, timeout=3.0)
            sources = normalize_sources(self.settings, self.language)
            changed, observed = check_source_updates(sources, self.settings.get("source_revisions"))
            self.ready.emit((changed, observed), release)
        except Exception:
            LOGGER.info("Update check unavailable", exc_info=True)
            self.ready.emit(([], {}), None)


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
    smoke_mode = "--startup-smoke-test" in sys.argv
    try:
        settings = JsonStore().load_settings()
    except Exception:
        settings = {}
    configure_logging(bool(settings.get("diagnostic_logging", False)), str(settings.get("log_level", "INFO")))
    LOGGER.info("Application startup requested")
    if not smoke_mode and not is_admin():
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

    if not smoke_mode and not acquire_single_instance():
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, "dicodePing هم اکنون در حال اجرا است.", "dicodePing", 0x40)
        except Exception:
            pass
        return 0

    if not smoke_mode:
        cleanup_stale_owned_process()
    set_app_id()

    qt_args = [argument for argument in sys.argv if argument != "--startup-smoke-test"]
    app = QApplication(qt_args)
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

    if smoke_mode:
        try:
            smoke_settings = dict(settings)
            smoke_settings.update({"language": "en", "accepted_disclaimer": True})
            window = MainWindow(
                preloaded_servers=[],
                preloaded_settings=smoke_settings,
                startup_prepared=True,
            )
            window.show()
        except Exception:
            LOGGER.exception("Packaged startup smoke test failed")
            report_path = os.environ.get("DICODEPING_STARTUP_SMOKE_REPORT", "").strip()
            if report_path:
                try:
                    Path(report_path).write_text(traceback.format_exc(), encoding="utf-8")
                except OSError:
                    pass
            return 2

        def finish_smoke_test() -> None:
            visible = window.isVisible()
            window._is_closing = True
            window.close()
            app.exit(0 if visible else 3)

        QTimer.singleShot(700, finish_smoke_test)
        return app.exec()

    splash = StartupSplash(language)
    if not application_icon.isNull():
        splash.setWindowIcon(application_icon)
    splash.show()
    screen = app.primaryScreen()
    if screen:
        splash.move(screen.availableGeometry().center() - splash.rect().center())

    state: dict[str, Any] = {"window": None, "worker": None, "update_worker": None}
    gate = StartupGate()
    worker = StartupPrepareThread(language)
    state["worker"] = worker
    worker.stage.connect(lambda value, fa, en: splash.set_stage(value, fa, en, language))

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.setInterval(4000)

    def prepared(
        servers: object,
        prepared_settings: object,
        startup_error: str,
        refresh_due: bool,
    ) -> None:
        if not gate.claim():
            return
        watchdog.stop()
        rows = startup_rows(servers)
        loaded_settings = dict(prepared_settings) if isinstance(prepared_settings, dict) else settings
        try:
            # Hydrate cached rows after the window becomes responsive. Building
            # a large table inside this signal used to freeze the splash.
            window = MainWindow(
                preloaded_servers=[],
                preloaded_settings=loaded_settings,
                startup_prepared=True,
                startup_error=startup_error,
            )
            state["window"] = window
            splash.set_stage(100, "آماده", "Ready", language)
            window.show()
            if is_windows():
                QTimer.singleShot(0, lambda: apply_native_window_icon(window, ASSET_DIR / "app.ico"))

            def hydrate_and_refresh() -> None:
                try:
                    window.servers = rows
                    window.render_servers()
                except Exception:
                    LOGGER.exception("Deferred server list hydration failed")

                def start_deferred_refresh() -> None:
                    if not window.isVisible():
                        return
                    if not window.settings.get("accepted_disclaimer"):
                        QTimer.singleShot(500, start_deferred_refresh)
                        return
                    should_scan = (
                        bool(window.settings.get("auto_scan_empty", True))
                        or not rows
                        or refresh_due
                    )
                    if should_scan and not window.worker and not window.manager.connected:
                        splash.set_indeterminate(
                            "در حال دریافت و آماده سازی سرورها...",
                            "Fetching and preparing servers...",
                            language,
                        )
                        window.start_scan()
                        startup_scan = window.worker
                        if startup_scan:
                            state["startup_scan"] = startup_scan
                            startup_scan.stage.connect(
                                lambda text: splash.set_indeterminate(text, text, language)
                            )

                            def server_rows_ready(*_args) -> None:
                                splash.set_stage(100, "سرورها آماده شدند", "Servers are ready", language)
                                QTimer.singleShot(180, splash.close)

                            startup_scan.preview_ready.connect(server_rows_ready)
                            startup_scan.success.connect(server_rows_ready)
                            startup_scan.failed.connect(lambda _message: splash.close())
                    elif rows:
                        QTimer.singleShot(350, splash.close)

                QTimer.singleShot(650, start_deferred_refresh)

                def check_updates() -> None:
                    if not window.isVisible():
                        return
                    update_worker = UpdateCheckThread(window.settings, window.language)
                    state["update_worker"] = update_worker

                    def offer(source_data: object, release: object) -> None:
                        changed, observed = source_data if isinstance(source_data, tuple) else ([], {})
                        if observed and not window.settings.get("source_revisions"):
                            window.settings["source_revisions"] = observed
                            window.store.save_settings(window.settings)
                        if changed:
                            names = "، ".join(item.name for item in changed[:3])
                            answer = QMessageBox.question(
                                window, APP_NAME,
                                (f"به‌روزرسانی منبع سرورها آماده است ({names}). اکنون دریافت شود؟"
                                 if window.language != "en" else
                                 f"A server source update is available ({names}). Download it now?"),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes,
                            )
                            if answer == QMessageBox.Yes:
                                window.settings["source_revisions"] = observed
                                window.store.save_settings(window.settings)
                                window.start_scan()
                        if release:
                            answer = QMessageBox.question(
                                window, APP_NAME,
                                (f"نسخه {release.tag} آماده است. صفحه دریافت باز شود؟"
                                 if window.language != "en" else
                                 f"Version {release.tag} is available. Open the download page?"),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes,
                            )
                            if answer == QMessageBox.Yes:
                                QDesktopServices.openUrl(QUrl(release.asset_url))

                    update_worker.ready.connect(offer)
                    update_worker.finished.connect(update_worker.deleteLater)
                    update_worker.start()

                # Start while the splash is still visible.  A watchdog closes
                # it soon after, so an unavailable update service cannot hold
                # the interface hostage.
                QTimer.singleShot(0, check_updates)

            QTimer.singleShot(80, hydrate_and_refresh)
        except Exception as exc:
            LOGGER.exception("Main window initialization failed")
            splash.close()
            message = (
                "راه‌اندازی رابط ناموفق بود. برنامه را دوباره اجرا کنید."
                if language != "en"
                else "The interface could not start. Please restart the application."
            )
            QMessageBox.critical(None, APP_NAME, f"{message}\n\n{exc}")
            QTimer.singleShot(0, lambda: app.exit(2))
        finally:
            # Discovery is shown on the splash but can never hold the app
            # indefinitely. The main window is already alive behind it.
            QTimer.singleShot(12000, splash.close)

    def preparation_timed_out() -> None:
        LOGGER.warning("Startup preparation timed out; opening the interface with safe defaults")
        prepared([], settings, "Startup preparation timed out", True)

    def worker_finished() -> None:
        if state.get("worker") is worker:
            state["worker"] = None
        worker.deleteLater()

    worker.ready.connect(prepared)
    worker.finished.connect(worker_finished)
    watchdog.timeout.connect(preparation_timed_out)
    worker.start()
    watchdog.start()

    def stop_startup_worker() -> None:
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(500)

    app.aboutToQuit.connect(stop_startup_worker)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
