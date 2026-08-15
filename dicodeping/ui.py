from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .constants import DEFAULT_SUBSCRIPTION_URL, RELEASE_VERSION
from .models import ServerRecord
from .scanner import ScanResult, run_scan
from .service import AppService
from .storage import JsonStore


APP_STYLE = r"""
* { font-family: 'Vazirmatn','Segoe UI'; font-size: 13px; }
QMainWindow, QWidget#AppSurface { background: #090B10; color: #EEF1F7; }
QWidget { color: #EEF1F7; }
QFrame#NavRail { background: #0D1017; border-right: 1px solid #1B2230; }
QFrame#TopBar { background: #0B0E14; border-bottom: 1px solid #1A202D; }
QLabel#Brand { font-size: 21px; font-weight: 800; letter-spacing: .3px; }
QLabel#PageTitle { font-size: 23px; font-weight: 800; }
QLabel#TitleXL { font-size: 30px; font-weight: 800; }
QLabel#TitleLG { font-size: 19px; font-weight: 700; }
QLabel#TitleMD { font-size: 15px; font-weight: 700; }
QLabel#Muted { color: #8E98AA; }
QLabel#Subtle { color: #667085; }
QLabel#AccentText { color: #8EA8FF; font-weight: 700; }
QLabel#StatusPill { background: #171D29; border: 1px solid #283247; border-radius: 8px; padding: 4px 9px; }
QFrame#Card { background: #10141C; border: 1px solid #202736; border-radius: 10px; }
QFrame#Hero { background: #111722; border: 1px solid #263147; border-radius: 12px; }
QFrame#Metric { background: #0F141D; border: 1px solid #202938; border-radius: 9px; }
QFrame#StatusDot { min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px; border-radius: 5px; background: #687386; }
QListWidget#NavList { background: transparent; border: 0; outline: 0; padding: 0; }
QListWidget#NavList::item { min-height: 28px; padding: 9px 12px; border-radius: 7px; color: #939DB0; margin: 2px 0; }
QListWidget#NavList::item:hover { background: #141A24; color: #C8D0DE; }
QListWidget#NavList::item:selected { background: #1B2540; color: #F5F7FB; font-weight: 700; }
QPushButton { background: #171D29; border: 1px solid #2A3447; border-radius: 7px; padding: 9px 14px; font-weight: 650; }
QPushButton:hover { background: #202838; border-color: #38465E; }
QPushButton:pressed { background: #121722; }
QPushButton:disabled { color: #5E6878; background: #11151D; border-color: #1D2330; }
QPushButton#Primary { background: #5577F5; border-color: #5577F5; color: white; }
QPushButton#Primary:hover { background: #6686FA; }
QPushButton#Danger { background: #351C25; border-color: #63303C; color: #FFBCC6; }
QPushButton#Ghost { background: transparent; border-color: #263042; }
QPushButton#NavAction { text-align: left; }
QLineEdit, QComboBox, QSpinBox { background: #0D1118; border: 1px solid #283247; border-radius: 7px; padding: 8px 10px; min-height: 20px; selection-background-color: #314D9A; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #5577F5; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QTableWidget { background: #0B0F15; alternate-background-color: #0E131B; border: 1px solid #202736; border-radius: 8px; gridline-color: #1B2230; selection-background-color: #1B2C55; selection-color: #FFFFFF; outline: 0; }
QTableWidget::item { padding: 7px; }
QHeaderView::section { background: #121721; color: #9BA5B6; border: 0; border-bottom: 1px solid #253044; padding: 9px 8px; font-weight: 700; }
QPlainTextEdit { background: #080B10; border: 1px solid #202736; border-radius: 8px; padding: 10px; font-family: 'Cascadia Mono','Consolas',monospace; color: #D6DCE6; selection-background-color: #314D9A; }
QProgressBar { background: #151A23; border: 0; border-radius: 3px; min-height: 6px; max-height: 6px; text-align: center; }
QProgressBar::chunk { background: #5577F5; border-radius: 3px; }
QScrollArea { border: 0; background: transparent; }
"""


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.result.emit(self.fn())
        except Exception as exc:
            traceback.print_exc()
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


def label(text: str, object_name: str = "") -> QLabel:
    node = QLabel(text)
    if object_name:
        node.setObjectName(object_name)
    node.setWordWrap(True)
    return node


def muted(text: str) -> QLabel:
    return label(text, "Muted")


def card(*, hero: bool = False) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Hero" if hero else "Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18 if not hero else 24, 17 if not hero else 22, 18 if not hero else 24, 17 if not hero else 22)
    layout.setSpacing(11)
    return frame, layout


def metric(title: str) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("Metric")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 13, 16, 13)
    layout.setSpacing(3)
    layout.addWidget(muted(title))
    value = label("—", "TitleLG")
    layout.addWidget(value)
    return frame, value


def fmt_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def safe_text(value: Any, fallback: str = "—") -> str:
    text = str(value or "").strip()
    return text or fallback


class OverviewPage(QWidget):
    connect_clicked = Signal()
    profiles_clicked = Signal()
    refresh_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(16)

        intro = QHBoxLayout()
        intro_text = QVBoxLayout()
        intro_text.setSpacing(2)
        intro_text.addWidget(label("مرکز اتصال", "TitleXL"))
        intro_text.addWidget(muted("پروفایل، مسیر، DNS و وضعیت runtime در یک نمای ساده."))
        intro.addLayout(intro_text)
        intro.addStretch(1)
        refresh = QPushButton("تازه‌سازی")
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self.refresh_clicked)
        intro.addWidget(refresh)
        root.addLayout(intro)

        hero, body = card(hero=True)
        status_line = QHBoxLayout()
        self.dot = QFrame(); self.dot.setObjectName("StatusDot")
        self.status = label("آماده اتصال", "TitleMD")
        self.mode_badge = label("SYSTEM PROXY", "StatusPill")
        status_line.addWidget(self.dot)
        status_line.addWidget(self.status)
        status_line.addStretch(1)
        status_line.addWidget(self.mode_badge)
        body.addLayout(status_line)

        self.server_name = label("سروری انتخاب نشده", "TitleXL")
        body.addWidget(self.server_name)
        self.server_meta = muted("Subscription را تازه‌سازی کنید و یک پروفایل را انتخاب کنید.")
        body.addWidget(self.server_meta)

        actions = QHBoxLayout()
        self.connect_btn = QPushButton("اتصال")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.setMinimumHeight(46)
        self.connect_btn.setMinimumWidth(150)
        self.connect_btn.clicked.connect(self.connect_clicked)
        profiles = QPushButton("مدیریت پروفایل‌ها")
        profiles.setObjectName("Ghost")
        profiles.setMinimumHeight(46)
        profiles.clicked.connect(self.profiles_clicked)
        actions.addWidget(self.connect_btn)
        actions.addWidget(profiles)
        actions.addStretch(1)
        body.addLayout(actions)
        root.addWidget(hero)

        metrics = QHBoxLayout()
        latency_card, self.latency_value = metric("تاخیر واقعی")
        download_card, self.download_value = metric("دریافت")
        upload_card, self.upload_value = metric("ارسال")
        core_card, self.core_value = metric("Core")
        for widget in (latency_card, download_card, upload_card, core_card):
            metrics.addWidget(widget, 1)
        root.addLayout(metrics)

        details, details_layout = card()
        head = QHBoxLayout()
        head.addWidget(label("پروفایل فعال", "TitleMD"))
        head.addStretch(1)
        self.source_value = label("—", "AccentText")
        head.addWidget(self.source_value)
        details_layout.addLayout(head)
        self.details = muted("—")
        details_layout.addWidget(self.details)
        root.addWidget(details)
        root.addStretch(1)

    def set_mode(self, tun: bool, system_proxy: str) -> None:
        if tun:
            self.mode_badge.setText("TUN")
        else:
            text = system_proxy.upper().replace("FORCEDCHANGE", "SYSTEM PROXY").replace("FORCEDCLEAR", "PROXY OFF")
            self.mode_badge.setText(text or "SYSTEM PROXY")

    def set_connected(self, connected: bool, connecting: bool = False) -> None:
        if connecting:
            self.status.setText("در حال برقراری اتصال…")
            self.dot.setStyleSheet("background:#EAB75B")
            self.connect_btn.setText("در حال اتصال…")
            self.connect_btn.setEnabled(False)
            return
        if connected:
            self.status.setText("متصل")
            self.dot.setStyleSheet("background:#39C890")
            self.connect_btn.setText("قطع اتصال")
            self.connect_btn.setObjectName("Danger")
        else:
            self.status.setText("آماده اتصال")
            self.dot.setStyleSheet("background:#687386")
            self.connect_btn.setText("اتصال")
            self.connect_btn.setObjectName("Primary")
        self.connect_btn.setEnabled(True)
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)

    def set_server(self, row: ServerRecord | None) -> None:
        if row is None:
            self.server_name.setText("سروری انتخاب نشده")
            self.server_meta.setText("Subscription را تازه‌سازی کنید و یک پروفایل را انتخاب کنید.")
            self.details.setText("—")
            self.source_value.setText("—")
            self.latency_value.setText("—")
            return
        self.server_name.setText(row.name)
        latency = f"{row.ping_ms} ms" if row.ping_ms is not None else "تست نشده"
        transport = row.network or "default"
        security = row.transport_security or "default"
        self.server_meta.setText(f"{row.protocol}  •  {row.host}:{row.port}  •  {latency}")
        self.details.setText(f"Transport: {transport}    Security: {security}    Status: {row.status}")
        self.source_value.setText(row.source_name)
        self.latency_value.setText(f"{row.ping_ms} ms" if row.ping_ms is not None else "—")

    def set_stats(self, stats: dict[str, Any]) -> None:
        self.download_value.setText(fmt_bytes(stats.get("download_bps")) + "/s")
        self.upload_value.setText(fmt_bytes(stats.get("upload_bps")) + "/s")

    def set_core(self, value: str) -> None:
        self.core_value.setText(value or "—")


class ProfilesPage(QWidget):
    refresh_clicked = Signal()
    latency_clicked = Signal()
    selection_changed = Signal(str)
    connect_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[ServerRecord] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(13)

        top = QHBoxLayout()
        left = QVBoxLayout(); left.setSpacing(2)
        left.addWidget(label("پروفایل‌ها", "TitleXL"))
        self.summary = muted("پروفایل‌های Subscription اصلی و Scanner")
        left.addWidget(self.summary)
        top.addLayout(left)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جست‌وجوی نام، آدرس، پروتکل…")
        self.search.setMinimumWidth(290)
        self.search.textChanged.connect(self._render)
        top.addWidget(self.search)
        root.addLayout(top)

        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("دریافت Subscription")
        self.refresh_btn.setObjectName("Primary")
        self.refresh_btn.clicked.connect(self.refresh_clicked)
        self.latency_btn = QPushButton("Real Ping")
        self.latency_btn.clicked.connect(self.latency_clicked)
        self.connect_btn = QPushButton("اتصال به انتخاب")
        self.connect_btn.setObjectName("Ghost")
        self.connect_btn.clicked.connect(self.connect_clicked)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.latency_btn)
        toolbar.addWidget(self.connect_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["نام", "پروتکل", "آدرس", "Transport", "Security", "Latency", "منبع"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col in (1, 3, 4, 5, 6):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._emit_selection)
        self.table.itemDoubleClicked.connect(lambda *_: self.connect_clicked.emit())
        root.addWidget(self.table, 1)

        details, details_layout = card()
        details_head = QHBoxLayout()
        details_head.addWidget(label("جزئیات پروفایل", "TitleMD"))
        details_head.addStretch(1)
        self.detail_latency = label("—", "AccentText")
        details_head.addWidget(self.detail_latency)
        details_layout.addLayout(details_head)
        self.details = muted("یک پروفایل را انتخاب کنید.")
        details_layout.addWidget(self.details)
        root.addWidget(details)

    def set_busy(self, busy: bool, text: str = "") -> None:
        for button in (self.refresh_btn, self.latency_btn, self.connect_btn):
            button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 100)
        if text:
            self.summary.setText(text)

    def set_rows(self, rows: list[ServerRecord], selected_id: str = "") -> None:
        self.rows = rows
        self.summary.setText(f"{len(rows)} پروفایل آماده")
        self._render(self.search.text(), selected_id=selected_id)

    def _render(self, _text: str = "", selected_id: str = "") -> None:
        needle = self.search.text().strip().casefold()
        visible = [
            r for r in self.rows
            if not needle or needle in f"{r.name} {r.host} {r.protocol} {r.network} {r.transport_security} {r.source_name}".casefold()
        ]
        self.table.blockSignals(True)
        self.table.setRowCount(len(visible))
        selected_row = -1
        for i, row in enumerate(visible):
            values = [
                row.name,
                row.protocol,
                f"{row.host}:{row.port}",
                row.network or "—",
                row.transport_security or "—",
                f"{row.ping_ms} ms" if row.ping_ms is not None else "—",
                row.source_name,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row.id)
                self.table.setItem(i, col, item)
            if selected_id and row.id == selected_id:
                selected_row = i
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self.table.blockSignals(False)
        self._update_details()

    def _emit_selection(self) -> None:
        items = self.table.selectedItems()
        if items:
            self.selection_changed.emit(str(items[0].data(Qt.ItemDataRole.UserRole) or ""))
        self._update_details()

    def _update_details(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.details.setText("یک پروفایل را انتخاب کنید.")
            self.detail_latency.setText("—")
            return
        server_id = str(items[0].data(Qt.ItemDataRole.UserRole) or "")
        row = next((r for r in self.rows if r.id == server_id), None)
        if row is None:
            return
        uri = row.config_blob
        if len(uri) > 180:
            uri = uri[:177] + "…"
        self.details.setText(
            f"{row.protocol} • {row.host}:{row.port} • {row.network or 'default'} • {row.transport_security or 'default'}\n{uri or 'Share URI توسط runtime ارائه نشده است.'}"
        )
        self.detail_latency.setText(f"{row.ping_ms} ms" if row.ping_ms is not None else row.status)


class ScannerPage(QWidget):
    start_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(14)
        top = QHBoxLayout()
        left = QVBoxLayout(); left.setSpacing(2)
        left.addWidget(label("Scanner", "TitleXL"))
        self.note = muted("کشف کانفیگ، bootstrap از runtime، بررسی مسیر Telegram و Real Ping.")
        left.addWidget(self.note)
        top.addLayout(left); top.addStretch(1)
        self.start = QPushButton("شروع اسکن")
        self.start.setObjectName("Primary")
        self.start.clicked.connect(self.start_clicked)
        top.addWidget(self.start)
        root.addLayout(top)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        root.addWidget(self.progress)
        panel, panel_layout = card()
        panel_layout.addWidget(label("جریان اجرا", "TitleMD"))
        self.editor = QPlainTextEdit(); self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("رویدادهای Scanner اینجا نمایش داده می‌شوند.")
        panel_layout.addWidget(self.editor, 1)
        root.addWidget(panel, 1)

    def set_busy(self, busy: bool) -> None:
        self.start.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 100)
        if busy:
            self.note.setText("Scanner در حال اجرا است…")
            self.editor.setPlainText("Bootstrap → Telegram crawl → Disconnect → Real Ping → Save")

    def show_result(self, result: ScanResult, lines: list[str]) -> None:
        self.note.setText(f"{result.reachable_configs} کانفیگ سالم از {result.crawled_configs} کاندیدا ذخیره شد.")
        self.editor.setPlainText("\n".join(lines))


class RoutingPage(QWidget):
    save_clicked = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(15)
        root.addWidget(label("Routing & DNS", "TitleXL"))
        root.addWidget(muted("تنظیمات شبکه بدون درگیر کردن مستقیم رابط با processهای core."))

        mode, mode_layout = card()
        mode_layout.addWidget(label("حالت اتصال", "TitleMD"))
        mode_row = QHBoxLayout()
        self.tun = QCheckBox("TUN mode")
        self.auto_route = QCheckBox("Auto route")
        self.strict_route = QCheckBox("Strict route")
        mode_row.addWidget(self.tun)
        mode_row.addWidget(self.auto_route)
        mode_row.addWidget(self.strict_route)
        mode_row.addStretch(1)
        mode_layout.addLayout(mode_row)
        mode_layout.addWidget(muted("در TUN mode مسیر سراسری توسط runtime مدیریت می‌شود. در بعضی سیستم‌ها مجوز مدیریتی لازم است."))
        root.addWidget(mode)

        proxy, proxy_layout = card()
        proxy_layout.addWidget(label("Core و پروکسی سیستم", "TitleMD"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Core"))
        self.core_preference = QComboBox()
        self.core_preference.addItem("خودکار / بهترین گزینه", "auto")
        self.core_preference.addItem("Xray", "xray")
        self.core_preference.addItem("sing-box", "sing_box")
        row.addWidget(self.core_preference, 1)
        row.addWidget(QLabel("System proxy"))
        self.system_proxy = QComboBox()
        self.system_proxy.addItem("فعال", "on")
        self.system_proxy.addItem("خاموش / پاک‌سازی", "off")
        self.system_proxy.addItem("بدون تغییر", "unchanged")
        self.system_proxy.addItem("PAC (Windows)", "pac")
        row.addWidget(self.system_proxy, 1)
        proxy_layout.addLayout(row)
        proxy_layout.addWidget(muted("در حالت خودکار، نوع پروفایل مسیر مناسب را انتخاب می‌کند؛ انتخاب دستی برای عیب‌یابی و سازگاری بیشتر است."))
        root.addWidget(proxy)

        dns, dns_layout = card()
        dns_layout.addWidget(label("DNS Strategy", "TitleMD"))
        dns_row = QHBoxLayout()
        self.dns_strategy = QComboBox()
        self.dns_strategy.addItem("As-Is", "AsIs")
        self.dns_strategy.addItem("IP if no match", "IPIfNonMatch")
        self.dns_strategy.addItem("IP on demand", "IPOnDemand")
        self.dns_preference = QComboBox()
        self.dns_preference.addItem("خودکار", "")
        self.dns_preference.addItem("ترجیح IPv4", "prefer_ipv4")
        self.dns_preference.addItem("ترجیح IPv6", "prefer_ipv6")
        self.dns_preference.addItem("فقط IPv4", "ipv4_only")
        self.dns_preference.addItem("فقط IPv6", "ipv6_only")
        dns_row.addWidget(self.dns_strategy, 1)
        dns_row.addWidget(self.dns_preference, 1)
        dns_layout.addLayout(dns_row)
        root.addWidget(dns)

        advanced, advanced_layout = card()
        advanced_layout.addWidget(label("Runtime", "TitleMD"))
        runtime_row = QHBoxLayout()
        runtime_row.addWidget(QLabel("TUN MTU"))
        self.mtu = QSpinBox(); self.mtu.setRange(1280, 9000); self.mtu.setValue(1500)
        runtime_row.addWidget(self.mtu)
        self.log_enabled = QCheckBox("ثبت گزارش runtime"); self.log_enabled.setChecked(True)
        runtime_row.addWidget(self.log_enabled)
        runtime_row.addStretch(1)
        advanced_layout.addLayout(runtime_row)
        root.addWidget(advanced)

        save = QPushButton("اعمال تنظیمات")
        save.setObjectName("Primary")
        save.setMinimumHeight(44)
        save.clicked.connect(self._save)
        root.addWidget(save)
        root.addStretch(1)

    def apply(self, settings: dict[str, Any]) -> None:
        core = self.core_preference.findData(str(settings.get("core_preference", "auto")))
        self.core_preference.setCurrentIndex(core if core >= 0 else 0)
        self.tun.setChecked(bool(settings.get("tun", False)))
        self.auto_route.setChecked(bool(settings.get("auto_route", True)))
        self.strict_route.setChecked(bool(settings.get("strict_route", True)))
        proxy = str(settings.get("system_proxy", "ForcedChange")).lower()
        proxy = {"forcedchange": "on", "forcedclear": "off", "unchanged": "unchanged", "pac": "pac"}.get(proxy, proxy)
        index = self.system_proxy.findData(proxy)
        self.system_proxy.setCurrentIndex(index if index >= 0 else 0)
        dns = self.dns_strategy.findData(str(settings.get("dns_strategy", "AsIs")))
        self.dns_strategy.setCurrentIndex(dns if dns >= 0 else 0)
        pref = self.dns_preference.findData(str(settings.get("dns_preference", "")))
        self.dns_preference.setCurrentIndex(pref if pref >= 0 else 0)
        self.mtu.setValue(int(settings.get("mtu", 1500) or 1500))
        self.log_enabled.setChecked(bool(settings.get("log_enabled", True)))

    def values(self) -> dict[str, Any]:
        return {
            "core_preference": self.core_preference.currentData(),
            "tun": self.tun.isChecked(),
            "auto_route": self.auto_route.isChecked(),
            "strict_route": self.strict_route.isChecked(),
            "system_proxy": self.system_proxy.currentData(),
            "dns_strategy": self.dns_strategy.currentData(),
            "dns_preference": self.dns_preference.currentData(),
            "mtu": self.mtu.value(),
            "log_enabled": self.log_enabled.isChecked(),
        }

    def _save(self) -> None:
        self.save_clicked.emit(self.values())


class LogsPage(QWidget):
    refresh_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(13)
        top = QHBoxLayout()
        left = QVBoxLayout(); left.setSpacing(2)
        left.addWidget(label("Runtime Logs", "TitleXL"))
        left.addWidget(muted("خروجی lifecycle، core و وضعیت اتصال."))
        top.addLayout(left); top.addStretch(1)
        button = QPushButton("تازه‌سازی")
        button.clicked.connect(self.refresh_clicked)
        top.addWidget(button)
        root.addLayout(top)
        self.editor = QPlainTextEdit(); self.editor.setReadOnly(True)
        root.addWidget(self.editor, 1)

    def set_lines(self, lines: list[str]) -> None:
        self.editor.setPlainText("\n".join(lines))
        bar = self.editor.verticalScrollBar(); bar.setValue(bar.maximum())


class AboutPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(16)
        root.addWidget(label("درباره", "TitleXL"))
        hero, body = card(hero=True)
        body.addWidget(label("dicodePing", "TitleXL"))
        body.addWidget(label(RELEASE_VERSION, "AccentText"))
        body.addWidget(muted("Version 3 pre-release • رابط و لایه محصول مستقل • runtime شبکه ماژولار"))
        root.addWidget(hero)
        info, layout = card()
        layout.addWidget(label("Subscription اصلی", "TitleMD"))
        layout.addWidget(muted(DEFAULT_SUBSCRIPTION_URL))
        layout.addWidget(label("مجوزها و اجزای متن‌باز", "TitleMD"))
        layout.addWidget(muted("اطلاعات کامل مجوزها و corresponding source در THIRD_PARTY_NOTICES.md و پوشه licenses قرار دارد."))
        root.addWidget(info)
        root.addStretch(1)


class MainWindow(QMainWindow):
    NAV_ITEMS = (
        ("اتصال", "overview"),
        ("پروفایل‌ها", "profiles"),
        ("Scanner", "scanner"),
        ("Routing & DNS", "routing"),
        ("Logs", "logs"),
        ("درباره", "about"),
    )

    def __init__(self, service: AppService, store: JsonStore) -> None:
        super().__init__()
        self.service = service
        self.store = store
        self.pool = QThreadPool.globalInstance()
        self.connected = False
        self.selected: ServerRecord | None = None
        self._last_runtime_settings: dict[str, Any] = {}
        self.setWindowTitle(f"dicodePing {RELEASE_VERSION}")
        self.resize(1260, 790)
        self.setMinimumSize(980, 650)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._load_cached()
        self._load_runtime_settings()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(2500)
        self.status_timer.timeout.connect(self._poll_runtime)
        self.status_timer.start()
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(1200)
        self.stats_timer.timeout.connect(self._poll_stats)
        self.stats_timer.start()
        if not self.service.servers():
            QTimer.singleShot(300, self.refresh_subscription)

    def _build_ui(self) -> None:
        surface = QWidget(); surface.setObjectName("AppSurface")
        outer = QHBoxLayout(surface); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        rail = QFrame(); rail.setObjectName("NavRail"); rail.setFixedWidth(228)
        rail_layout = QVBoxLayout(rail); rail_layout.setContentsMargins(16, 20, 16, 16); rail_layout.setSpacing(10)
        brand_row = QHBoxLayout()
        brand_row.addWidget(label("dicodePing", "Brand")); brand_row.addStretch(1)
        version = label("V3", "StatusPill"); brand_row.addWidget(version)
        rail_layout.addLayout(brand_row)
        rail_layout.addWidget(muted(RELEASE_VERSION))
        rail_layout.addSpacing(8)

        self.nav = QListWidget(); self.nav.setObjectName("NavList")
        for title, _ in self.NAV_ITEMS:
            self.nav.addItem(QListWidgetItem(title))
        self.nav.setCurrentRow(0)
        rail_layout.addWidget(self.nav, 1)

        runtime_card, runtime_layout = card()
        runtime_layout.setContentsMargins(12, 11, 12, 11)
        runtime_layout.addWidget(label("Runtime", "TitleMD"))
        self.runtime_label = muted("در حال راه‌اندازی")
        runtime_layout.addWidget(self.runtime_label)
        rail_layout.addWidget(runtime_card)
        outer.addWidget(rail)

        content = QVBoxLayout(); content.setContentsMargins(0, 0, 0, 0); content.setSpacing(0)
        topbar = QFrame(); topbar.setObjectName("TopBar"); topbar.setFixedHeight(58)
        top = QHBoxLayout(topbar); top.setContentsMargins(24, 0, 24, 0)
        self.page_title = label("اتصال", "PageTitle")
        top.addWidget(self.page_title); top.addStretch(1)
        self.connection_pill = label("OFFLINE", "StatusPill")
        top.addWidget(self.connection_pill)
        content.addWidget(topbar)

        self.stack = QStackedWidget()
        self.overview = OverviewPage()
        self.profiles = ProfilesPage()
        self.scanner = ScannerPage()
        self.routing = RoutingPage()
        self.logs = LogsPage()
        self.about = AboutPage()
        for page in (self.overview, self.profiles, self.scanner, self.routing, self.logs, self.about):
            self.stack.addWidget(page)
        content.addWidget(self.stack, 1)
        outer.addLayout(content, 1)
        self.setCentralWidget(surface)

        self.nav.currentRowChanged.connect(self._navigate)
        self.overview.connect_clicked.connect(self.toggle_connection)
        self.overview.profiles_clicked.connect(lambda: self.nav.setCurrentRow(1))
        self.overview.refresh_clicked.connect(self.refresh_subscription)
        self.profiles.refresh_clicked.connect(self.refresh_subscription)
        self.profiles.latency_clicked.connect(self.test_latency)
        self.profiles.selection_changed.connect(self.select_server)
        self.profiles.connect_clicked.connect(self.toggle_connection)
        self.scanner.start_clicked.connect(self.start_scanner)
        self.routing.save_clicked.connect(self.save_runtime_settings)
        self.logs.refresh_clicked.connect(self.refresh_logs)

    def _navigate(self, index: int) -> None:
        if index < 0 or index >= len(self.NAV_ITEMS):
            return
        self.stack.setCurrentIndex(index)
        self.page_title.setText(self.NAV_ITEMS[index][0])
        if index == 4:
            self.refresh_logs()

    def run_worker(
        self,
        fn: Callable[[], Any],
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        worker = Worker(fn)
        if on_result:
            worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error or self.show_error)
        if on_finished:
            worker.signals.finished.connect(on_finished)
        self.pool.start(worker)

    def _load_cached(self) -> None:
        rows = self.service.servers()
        selected_id = str(self.store.load_settings().get("selected_server_id") or "")
        self.selected = next((r for r in rows if r.id == selected_id), None) or (rows[0] if rows else None)
        self.profiles.set_rows(rows, self.selected.id if self.selected else "")
        self.overview.set_server(self.selected)

    def refresh_subscription(self) -> None:
        self.profiles.set_busy(True, "در حال دریافت و پردازش Subscription…")
        self.run_worker(
            lambda: self.service.refresh(language="fa"),
            self._refresh_done,
            self.show_error,
            lambda: self.profiles.set_busy(False),
        )

    def _refresh_done(self, rows: object) -> None:
        rows = list(rows) if isinstance(rows, list) else []
        selected_id = self.selected.id if self.selected else str(self.store.load_settings().get("selected_server_id") or "")
        self.selected = next((r for r in rows if r.id == selected_id), None) or (rows[0] if rows else None)
        self.profiles.set_rows(rows, self.selected.id if self.selected else "")
        self.overview.set_server(self.selected)
        self.runtime_label.setText("آماده")

    def select_server(self, server_id: str) -> None:
        row = next((r for r in self.service.servers() if r.id == server_id), None)
        if row is None:
            return
        self.selected = row
        self.overview.set_server(row)
        settings = self.store.load_settings()
        settings["selected_server_id"] = row.id
        self.store.save_settings(settings)

    def toggle_connection(self) -> None:
        if self.connected:
            self.overview.set_connected(False, connecting=True)
            self.run_worker(self.service.disconnect, lambda _: self._set_connected(False), self._connection_error)
            return
        if self.selected is None:
            self.show_error("هیچ پروفایلی انتخاب نشده است.")
            self.nav.setCurrentRow(1)
            return
        values = self.routing.values()
        selected = self.selected
        self.overview.set_connected(False, connecting=True)
        self.run_worker(
            lambda: self.service.connect(selected, tun=bool(values["tun"]), system_proxy=str(values["system_proxy"])),
            lambda _: self._set_connected(True),
            self._connection_error,
        )

    def _set_connected(self, value: bool) -> None:
        self.connected = value
        self.overview.set_connected(value)
        self.connection_pill.setText("CONNECTED" if value else "OFFLINE")
        self.runtime_label.setText("متصل" if value else "آماده")
        if value:
            self.refresh_logs()

    def _connection_error(self, message: str) -> None:
        self._set_connected(False)
        self.show_error(message)

    def start_scanner(self) -> None:
        self.scanner.set_busy(True)
        messages: list[str] = []

        def work() -> tuple[ScanResult, list[str]]:
            result = run_scan(self.service, log=messages.append)
            return result, messages

        def done(payload: object) -> None:
            if not isinstance(payload, tuple) or len(payload) != 2:
                return
            result, lines = payload
            if isinstance(result, ScanResult):
                self.scanner.show_result(result, list(lines))
                self._load_cached()

        self.run_worker(work, done, self.show_error, lambda: self.scanner.set_busy(False))

    def test_latency(self) -> None:
        rows = self.service.servers()
        if not rows:
            return
        self.profiles.set_busy(True, "Real Ping در حال اندازه‌گیری است…")
        self.run_worker(
            lambda: self.service.test_latency(rows),
            self._latency_done,
            self.show_error,
            lambda: self.profiles.set_busy(False),
        )

    def _latency_done(self, rows: object) -> None:
        rows = list(rows) if isinstance(rows, list) else []
        selected_id = self.selected.id if self.selected else ""
        self.profiles.set_rows(rows, selected_id)
        self.selected = next((r for r in rows if r.id == selected_id), self.selected)
        self.overview.set_server(self.selected)
        reachable = sum(1 for r in rows if r.ping_ms is not None)
        self.profiles.summary.setText(f"Real Ping کامل شد • {reachable}/{len(rows)} پاسخ‌گو")

    def _load_runtime_settings(self) -> None:
        def done(settings: object) -> None:
            if not isinstance(settings, dict):
                return
            self._last_runtime_settings = settings
            self.routing.apply(settings)
            self.overview.set_mode(bool(settings.get("tun", False)), str(settings.get("system_proxy", "ForcedChange")))
            self.runtime_label.setText("آماده")

        self.run_worker(self.service.runtime.settings_get, done, lambda _e: self.runtime_label.setText("در دسترس نیست"))

    def save_runtime_settings(self, values: dict[str, Any]) -> None:
        def done(result: object) -> None:
            if isinstance(result, dict):
                self._last_runtime_settings = result
                self.routing.apply(result)
                self.overview.set_mode(bool(result.get("tun", False)), str(result.get("system_proxy", "ForcedChange")))
            local = self.store.load_settings()
            local.update({"tun": values.get("tun"), "system_proxy": values.get("system_proxy")})
            self.store.save_settings(local)

        self.run_worker(lambda: self.service.runtime.settings_set(**values), done)

    def _poll_runtime(self) -> None:
        if not self.service.runtime.running:
            return
        self.run_worker(self.service.runtime.status, self._status_result, lambda _e: None)

    def _status_result(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        running = bool(result.get("connected"))
        self.overview.set_core(safe_text(result.get("running_core")))
        self.overview.set_mode(bool(result.get("tun", False)), str(result.get("system_proxy", "")))
        if running != self.connected:
            self._set_connected(running)

    def _poll_stats(self) -> None:
        if not self.connected or not self.service.runtime.running:
            return
        self.run_worker(
            self.service.runtime.stats,
            lambda result: self.overview.set_stats(result) if isinstance(result, dict) else None,
            lambda _e: None,
        )

    def refresh_logs(self) -> None:
        self.run_worker(
            lambda: self.service.runtime.logs(600),
            lambda lines: self.logs.set_lines(lines if isinstance(lines, list) else []),
            lambda _e: None,
        )

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "dicodePing", message or "خطای نامشخص")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.service.runtime.close()
        except Exception:
            pass
        event.accept()
