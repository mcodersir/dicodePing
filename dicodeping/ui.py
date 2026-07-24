from __future__ import annotations

import time
from functools import partial
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QDesktopServices, QIcon, QMouseEvent, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSpinBox,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .constants import ASSET_DIR, DEFAULT_SUBSCRIPTION_URL, LOG_FILE, MAX_CUSTOM_SUBSCRIPTIONS
from .diagnostics import get_logger
from .i18n import tr
from .models import ServerRecord, SourceDefinition
from .protocols import blob_to_config, config_to_blob, set_display_name
from .service import ServerService
from .sources import normalize_sources, serialize_sources, source_id_for_url
from .storage import JsonStore
from .workers import ApplicationUpdateThread, ConnectionMonitorThread, ConnectThread, DiscoverThread, RefreshSubsetThread, RefreshThread
from .xray import XrayManager, normalize_bypass_domains

LOGGER = get_logger("ui")


DARK = {
    "window": "#070A0F",
    "shell": "#0B0F15",
    "sidebar": "#090D13",
    "surface": "#111720",
    "surface2": "#151C26",
    "surface3": "#1B2430",
    "border": "#222D3B",
    "border2": "#2E3A4A",
    "text": "#F4F7FB",
    "muted": "#8F9CAD",
    "muted2": "#687588",
    "accent": "#6D8EFF",
    "accentHover": "#7E9BFF",
    "accentSoft": "#19233E",
    "success": "#4FD08A",
    "successSoft": "#10271D",
    "danger": "#FF7884",
    "dangerSoft": "#2B151B",
    "warning": "#F1B95A",
    "selection": "#1C2838",
}

LIGHT = {
    "window": "#E9EDF2",
    "shell": "#F8FAFC",
    "sidebar": "#F1F4F7",
    "surface": "#FFFFFF",
    "surface2": "#F7F9FC",
    "surface3": "#EDF1F6",
    "border": "#DDE3EA",
    "border2": "#CBD3DD",
    "text": "#151A22",
    "muted": "#667386",
    "muted2": "#8995A5",
    "accent": "#315FEA",
    "accentHover": "#244FD0",
    "accentSoft": "#E9EEFF",
    "success": "#178653",
    "successSoft": "#E7F6EE",
    "danger": "#C63F4C",
    "dangerSoft": "#FCECEF",
    "warning": "#A96E09",
    "selection": "#E8EEFA",
}


def build_stylesheet(theme: str) -> str:
    c = DARK if theme == "dark" else LIGHT
    return f"""
    * {{
        font-family: Vazirmatn, Vazir, Tahoma, Segoe UI;
        font-size: 13px;
        outline: none;
    }}
    QMainWindow {{ background: transparent; }}
    QWidget {{ color: {c['text']}; background: transparent; }}
    QWidget#windowRoot {{ background: transparent; }}
    QFrame#appShell {{
        background: {c['shell']}; border: 1px solid {c['border2']}; border-radius: 16px;
    }}
    QFrame#appShell[maximized="true"] {{ border: 0; border-radius: 0; }}
    QFrame#titleBar {{
        background: {c['shell']}; border: 0; border-bottom: 1px solid {c['border']};
        border-top-left-radius: 16px; border-top-right-radius: 16px;
    }}
    QFrame#sidebar {{ background: {c['sidebar']}; border: 0; border-right: 1px solid {c['border']}; }}
    QLabel#brandTitle {{ font-size: 16px; font-weight: 800; }}
    QLabel#brandSub, QLabel#muted, QLabel.pageSubtitle {{ color: {c['muted']}; }}
    QLabel#pageTitle {{ font-size: 23px; font-weight: 850; min-height: 34px; }}
    QLabel#sectionTitle {{ font-size: 16px; font-weight: 800; min-height: 28px; }}
    QLabel#heroTitle {{ font-size: 25px; font-weight: 900; min-height: 38px; }}
    QLabel#statValue {{ font-size: 23px; font-weight: 900; }}
    QLabel#statusOnline {{ color: {c['success']}; font-weight: 800; }}
    QLabel#statusOffline {{ color: {c['danger']}; font-weight: 800; }}
    QLabel#statusBusy {{ color: {c['warning']}; font-weight: 800; }}
    QLabel#tiny {{ color: {c['muted2']}; font-size: 11px; min-height: 18px; }}

    QFrame#card, QFrame#heroCard, QFrame#statCard, QFrame#toolbarCard,
    QFrame#settingCard, QFrame#aboutCard {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px;
    }}
    QFrame#heroCard {{ background: {c['surface2']}; }}
    QFrame#activityBar {{
        background: {c['accentSoft']}; border: 1px solid {c['border2']}; border-radius: 12px;
    }}
    QFrame#statusDot[status="online"] {{ background: {c['success']}; border-radius: 5px; }}
    QFrame#statusDot[status="offline"] {{ background: {c['danger']}; border-radius: 5px; }}
    QFrame#statusDot[status="busy"] {{ background: {c['warning']}; border-radius: 5px; }}
    QFrame#softPanel {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 11px; }}

    QPushButton {{
        min-height: 44px; max-height: 44px; padding: 0 15px; border: 1px solid {c['border2']}; border-radius: 10px;
        background: {c['surface2']}; color: {c['text']}; font-weight: 700;
    }}
    QPushButton:hover {{ background: {c['surface3']}; border-color: {c['muted2']}; }}
    QPushButton:pressed {{ padding-top: 1px; background: {c['selection']}; }}
    QPushButton:disabled {{ color: {c['muted2']}; background: {c['surface']}; border-color: {c['border']}; }}
    QPushButton[kind="primary"] {{ background: {c['accent']}; color: #FFFFFF; border-color: {c['accent']}; font-weight: 850; }}
    QPushButton[kind="primary"]:hover {{ background: {c['accentHover']}; border-color: {c['accentHover']}; }}
    QPushButton[kind="danger"] {{ color: {c['danger']}; background: {c['dangerSoft']}; border-color: {c['danger']}; }}
    QPushButton[kind="ghost"] {{ background: transparent; border-color: transparent; color: {c['muted']}; }}
    QPushButton[kind="ghost"]:hover {{ background: {c['surface3']}; color: {c['text']}; }}
    QPushButton#navButton {{
        min-height: 44px; max-height: 44px; padding: 0 14px; text-align: start; background: transparent;
        border-color: transparent; color: {c['muted']};
    }}
    QPushButton#navButton:hover {{ background: {c['surface2']}; color: {c['text']}; }}
    QPushButton#navButton:checked {{ background: {c['accent']}; color: #FFFFFF; border-color: {c['accent']}; }}
    QPushButton#windowButton, QPushButton#closeButton {{
        min-width: 36px; max-width: 36px; min-height: 32px; max-height: 32px;
        padding: 0; border: 0; border-radius: 8px; background: transparent;
    }}
    QPushButton#windowButton:hover {{ background: {c['surface3']}; }}
    QPushButton#closeButton:hover {{ background: #D94B58; }}
    QLabel#flagBadge {{
        min-width: 38px; max-width: 38px; min-height: 28px; max-height: 28px;
        border: 1px solid {c['border2']}; border-radius: 8px; background: {c['surface2']};
        font-family: "Segoe UI Emoji"; font-size: 18px; qproperty-alignment: AlignCenter;
    }}
    QPushButton#tableAction {{ min-height: 40px; max-height: 40px; padding: 0 13px; }}
    QPushButton#pinButton {{ min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; padding: 0; border-radius: 10px; font-size: 18px; color: {c['accent']}; }}

    QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {{
        min-height: 44px; padding: 0 13px; background: {c['surface2']}; color: {c['text']};
        border: 1px solid {c['border2']}; border-radius: 10px; selection-background-color: {c['accent']};
    }}
    QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover, QSpinBox:hover {{ border-color: {c['muted2']}; }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; background: {c['surface']}; }}
    QPlainTextEdit {{ padding: 10px 12px; min-height: 170px; }}
    QComboBox::drop-down {{ border: 0; width: 30px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: 0; background: transparent; }}
    QSpinBox::up-arrow, QSpinBox::down-arrow {{ width: 0px; height: 0px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border2']};
        border-radius: 9px; selection-background-color: {c['selection']}; padding: 6px;
    }}
    QListWidget {{
        background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border2']};
        border-radius: 10px; padding: 6px;
    }}
    QListWidget::item {{ min-height: 36px; padding: 4px 8px; border-radius: 7px; }}
    QListWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 12px; background: {c['surface']}; top: 0px; margin-top: 7px; }}
    QTabBar {{ background: transparent; border: 0; }}
    QTabBar::tab {{
        min-height: 38px; padding: 0 16px; margin: 0 0 0 7px;
        background: {c['surface2']}; color: {c['muted']}; border: 1px solid {c['border']};
        border-radius: 10px; font-weight: 750;
    }}
    QTabBar::tab:hover {{ color: {c['text']}; border-color: {c['muted2']}; }}
    QTabBar::tab:selected {{ background: {c['accentSoft']}; color: {c['text']}; border-color: {c['accent']}; }}
    QFrame#skeletonCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 13px; }}
    QFrame#skeletonBar {{ background: {c['surface3']}; border: 0; border-radius: 6px; }}
    QFrame#sidebarStatus {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 11px; }}
    QPushButton#linkButton {{
        min-height: 44px; text-align: start; background: {c['surface2']}; border-color: {c['border']};
    }}
    QPushButton#linkButton:hover {{ border-color: {c['accent']}; background: {c['accentSoft']}; }}
    QCheckBox {{ spacing: 10px; color: {c['text']}; min-height: 30px; }}
    QCheckBox::indicator {{ width: 20px; height: 20px; border: 1px solid {c['border2']}; border-radius: 6px; background: {c['surface2']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

    QTableWidget {{
        background: {c['surface']}; alternate-background-color: {c['surface2']};
        border: 1px solid {c['border']}; border-radius: 13px; gridline-color: transparent;
        selection-background-color: {c['selection']}; selection-color: {c['text']};
    }}
    QTableWidget::item {{ border-bottom: 1px solid {c['border']}; padding: 10px 8px; }}
    QHeaderView::section {{
        background: {c['surface2']}; color: {c['muted']}; border: 0; border-bottom: 1px solid {c['border']};
        padding: 11px; font-weight: 750;
    }}
    QProgressBar {{ min-height: 6px; max-height: 6px; background: {c['surface3']}; border: 0; border-radius: 3px; color: transparent; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border2']}; min-height: 44px; border-radius: 5px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['muted2']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px 4px; }}
    QScrollBar::handle:horizontal {{ background: {c['border2']}; min-width: 44px; border-radius: 5px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['muted2']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

    QFrame#dialogPanel {{ background: {c['surface']}; border: 1px solid {c['border2']}; border-radius: 16px; }}
    QLabel#dialogTitle {{ font-size: 18px; font-weight: 850; min-height: 30px; }}
    QLabel#dialogMessage {{ color: {c['muted']}; min-height: 48px; }}
    """


def icon(name: str) -> QIcon:
    return QIcon(str(ASSET_DIR / name))


def tinted_icon(name: str, color: str = "#FFFFFF", size: int = 24) -> QIcon:
    source = icon(name).pixmap(size, size)
    if source.isNull():
        return icon(name)
    painter = QPainter(source)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(source.rect(), QColor(color))
    painter.end()
    return QIcon(source)

def country_flag_pixmap(code: str, width: int = 34, height: int = 24) -> QPixmap:
    """Render a crisp offline flag badge without relying on emoji fonts."""
    code = (code or "").strip().upper()
    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#E9EDF3"))
    painter.drawRoundedRect(0, 0, width, height, 5, 5)

    def bands(colors, vertical=False):
        n = len(colors)
        for i, color in enumerate(colors):
            painter.setBrush(QColor(color))
            if vertical:
                x0 = round(i * width / n); x1 = round((i + 1) * width / n)
                painter.drawRect(x0, 0, x1 - x0, height)
            else:
                y0 = round(i * height / n); y1 = round((i + 1) * height / n)
                painter.drawRect(0, y0, width, y1 - y0)

    horizontal = {
        "DE": ["#000000", "#DD0000", "#FFCE00"], "NL": ["#AE1C28", "#FFFFFF", "#21468B"],
        "RU": ["#FFFFFF", "#0039A6", "#D52B1E"], "UA": ["#0057B7", "#FFD700"],
        "AT": ["#ED2939", "#FFFFFF", "#ED2939"], "PL": ["#FFFFFF", "#DC143C"],
        "HU": ["#CE2939", "#FFFFFF", "#477050"], "BG": ["#FFFFFF", "#00966E", "#D62612"],
        "EE": ["#0072CE", "#000000", "#FFFFFF"], "LT": ["#FDB913", "#006A44", "#C1272D"],
        "LV": ["#9E3039", "#FFFFFF", "#9E3039"], "LU": ["#EF3340", "#FFFFFF", "#00A3E0"],
        "TH": ["#A51931", "#FFFFFF", "#2D2A4A", "#2D2A4A", "#FFFFFF", "#A51931"],
        "ID": ["#FF0000", "#FFFFFF"], "MC": ["#CE1126", "#FFFFFF"],
        "RO": None, "FR": None, "IT": None, "IE": None, "BE": None,
    }
    vertical = {
        "FR": ["#0055A4", "#FFFFFF", "#EF4135"], "IT": ["#009246", "#FFFFFF", "#CE2B37"],
        "IE": ["#169B62", "#FFFFFF", "#FF883E"], "BE": ["#000000", "#FDDA24", "#EF3340"],
        "RO": ["#002B7F", "#FCD116", "#CE1126"], "MX": ["#006847", "#FFFFFF", "#CE1126"],
    }
    if code in vertical:
        bands(vertical[code], True)
    elif code in horizontal and horizontal[code]:
        bands(horizontal[code])
    elif code == "JP":
        bands(["#FFFFFF"]); painter.setBrush(QColor("#BC002D")); painter.drawEllipse(width//2-6, height//2-6, 12, 12)
    elif code == "TR":
        bands(["#E30A17"]); painter.setBrush(QColor("#FFFFFF")); painter.drawEllipse(8, 5, 13, 13); painter.setBrush(QColor("#E30A17")); painter.drawEllipse(11, 6, 11, 11)
    elif code == "IR":
        bands(["#239F40", "#FFFFFF", "#DA0000"]); painter.setBrush(QColor("#DA0000")); painter.drawEllipse(width//2-2, height//2-2, 4, 4)
    elif code in {"GB", "AU", "NZ"}:
        bands(["#012169"]); painter.setPen(QPen(QColor("#FFFFFF"), 5)); painter.drawLine(0,0,width,height); painter.drawLine(width,0,0,height); painter.setPen(QPen(QColor("#C8102E"), 2)); painter.drawLine(0,0,width,height); painter.drawLine(width,0,0,height); painter.setPen(QPen(QColor("#FFFFFF"), 7)); painter.drawLine(width//2,0,width//2,height); painter.drawLine(0,height//2,width,height//2); painter.setPen(QPen(QColor("#C8102E"), 4)); painter.drawLine(width//2,0,width//2,height); painter.drawLine(0,height//2,width,height//2)
    elif code == "US":
        bands((["#B22234", "#FFFFFF"] * 7)[:13]); painter.setPen(Qt.NoPen); painter.setBrush(QColor("#3C3B6E")); painter.drawRect(0,0,width//2,height//2+1)
    elif code == "CA":
        bands(["#D80621", "#FFFFFF", "#D80621"], True); painter.setBrush(QColor("#D80621")); painter.drawEllipse(width//2-3,height//2-4,6,8)
    elif code == "CH":
        bands(["#D52B1E"]); painter.setBrush(QColor("#FFFFFF")); painter.drawRect(width//2-2,5,4,height-10); painter.drawRect(9,height//2-2,width-18,4)
    elif code in {"SE", "FI", "NO", "DK"}:
        bg, cross = {"SE":("#006AA7","#FECC00"),"FI":("#FFFFFF","#003580"),"NO":("#BA0C2F","#FFFFFF"),"DK":("#C60C30","#FFFFFF")}[code]
        bands([bg]); painter.setBrush(QColor(cross)); painter.drawRect(10,0,4,height); painter.drawRect(0,height//2-2,width,4)
        if code == "NO":
            painter.setBrush(QColor("#00205B")); painter.drawRect(11,0,2,height); painter.drawRect(0,height//2-1,width,2)
    elif code in {"SG", "CN", "VN", "AE", "IN", "BR", "IL", "KR", "HK", "MY", "ZA", "ES", "PT", "CZ"}:
        # Simplified but recognizable local vector badges.
        palette={"SG":["#EF3340","#FFFFFF"],"CN":["#DE2910"],"VN":["#DA251D"],"AE":["#00732F","#FFFFFF","#000000"],"IN":["#FF9933","#FFFFFF","#138808"],"BR":["#009C3B"],"IL":["#FFFFFF"],"KR":["#FFFFFF"],"HK":["#DE2910"],"MY":["#CC0001","#FFFFFF"]*4,"ZA":["#007749"],"ES":["#AA151B","#F1BF00","#AA151B"],"PT":["#046A38","#DA291C"],"CZ":["#FFFFFF","#D7141A"]}
        bands(palette[code], code=="PT")
        if code in {"CN","VN","HK"}: painter.setBrush(QColor("#FFDE00")); painter.drawEllipse(7,6,5,5)
        elif code == "BR": painter.setBrush(QColor("#FFDF00")); painter.drawPolygon(QPoint(width//2,4), QPoint(width-5,height//2), QPoint(width//2,height-4), QPoint(5,height//2)); painter.setBrush(QColor("#002776")); painter.drawEllipse(width//2-5,height//2-5,10,10)
        elif code == "IN": painter.setBrush(QColor("#000080")); painter.drawEllipse(width//2-2,height//2-2,4,4)
        elif code == "IL": painter.setPen(QPen(QColor("#0038B8"),2)); painter.drawLine(0,5,width,5); painter.drawLine(0,height-5,width,height-5)
        elif code == "KR": painter.setBrush(QColor("#CD2E3A")); painter.drawEllipse(width//2-5,height//2-5,10,10)
    else:
        painter.setPen(QPen(QColor("#7C8A9A"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(8,3,width-16,height-6)
        painter.drawLine(width//2,3,width//2,height-3)
        painter.drawLine(7,height//2,width-7,height//2)
    painter.end()
    return pm



def format_bytes(value: int) -> str:
    size = max(0.0, float(value or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class FadeStackedWidget(QStackedWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._animation: QPropertyAnimation | None = None
        self._effect: QGraphicsOpacityEffect | None = None

    def fade_to(self, index: int) -> None:
        if index == self.currentIndex() or index < 0 or index >= self.count():
            return
        self.setCurrentIndex(index)
        target = self.currentWidget()
        effect = QGraphicsOpacityEffect(target)
        target.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        animation = QPropertyAnimation(effect, b"opacity", target)
        animation.setDuration(125)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def cleanup() -> None:
            target.setGraphicsEffect(None)
            self._effect = None
            self._animation = None

        animation.finished.connect(cleanup)
        self._effect = effect
        self._animation = animation
        animation.start()


class AppDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        *,
        accept_text: str,
        reject_text: str = "",
        danger: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(420)
        self.setMaximumWidth(580)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        panel = QFrame()
        panel.setObjectName("dialogPanel")
        root.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        title_label.setWordWrap(True)
        message_label = QLabel(message)
        message_label.setObjectName("dialogMessage")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title_label)
        layout.addWidget(message_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        if reject_text:
            reject = QPushButton(reject_text)
            reject.clicked.connect(self.reject)
            buttons.addWidget(reject)
        accept = QPushButton(accept_text)
        accept.setProperty("kind", "danger" if danger else "primary")
        accept.clicked.connect(self.accept)
        buttons.addWidget(accept)
        layout.addLayout(buttons)
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(140)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        QTimer.singleShot(0, self._fade.start)

    @classmethod
    def info(cls, parent: QWidget, title: str, message: str, ok_text: str = "باشه") -> None:
        cls(parent, title, message, accept_text=ok_text).exec()

    @classmethod
    def error(cls, parent: QWidget, title: str, message: str, ok_text: str = "باشه") -> None:
        cls(parent, title, message, accept_text=ok_text, danger=True).exec()

    @classmethod
    def confirm(
        cls,
        parent: QWidget,
        title: str,
        message: str,
        *,
        accept_text: str,
        reject_text: str,
        danger: bool = False,
    ) -> bool:
        return cls(
            parent,
            title,
            message,
            accept_text=accept_text,
            reject_text=reject_text,
            danger=danger,
        ).exec() == QDialog.Accepted


class AppInputDialog(AppDialog):
    def __init__(self, parent: QWidget, title: str, message: str, value: str, accept_text: str, reject_text: str) -> None:
        super().__init__(parent, title, message, accept_text=accept_text, reject_text=reject_text)
        panel = self.layout().itemAt(0).widget()
        layout = panel.layout()
        self.input = QLineEdit(value)
        self.input.setClearButtonEnabled(True)
        self.input.selectAll()
        layout.insertWidget(2, self.input)
        self.input.returnPressed.connect(self.accept)
        QTimer.singleShot(0, self.input.setFocus)

    @classmethod
    def get_text(cls, parent: QWidget, title: str, message: str, value: str, accept_text: str, reject_text: str) -> tuple[str, bool]:
        dialog = cls(parent, title, message, value, accept_text, reject_text)
        accepted = dialog.exec() == QDialog.Accepted
        return dialog.input.text().strip(), accepted


class TitleBar(QFrame):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(68)
        self._drag_position: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setDirection(QBoxLayout.RightToLeft)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        self.close_button = QPushButton()
        self.close_button.setObjectName("closeButton")
        self.close_button.setIcon(icon("close.svg"))
        self.close_button.clicked.connect(window.close)
        self.max_button = QPushButton()
        self.max_button.setObjectName("windowButton")
        self.max_button.setIcon(icon("maximize.svg"))
        self.max_button.clicked.connect(window.toggle_maximize)
        self.min_button = QPushButton()
        self.min_button.setObjectName("windowButton")
        self.min_button.setIcon(icon("minimize.svg"))
        self.min_button.clicked.connect(window.showMinimized)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        controls.addWidget(self.close_button)
        controls.addWidget(self.max_button)
        controls.addWidget(self.min_button)
        layout.addLayout(controls)
        layout.addStretch()

        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel(window.t("product"))
        self.title.setObjectName("brandTitle")
        self.subtitle = QLabel(window.t("app_subtitle"))
        self.subtitle.setObjectName("brandSub")
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        layout.addLayout(text)
        logo = QLabel()
        logo.setPixmap(icon("app.svg").pixmap(42, 42))
        layout.addWidget(logo)

    def set_maximized(self, maximized: bool) -> None:
        self.max_button.setIcon(icon("restore.svg" if maximized else "maximize.svg"))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not self.window.isMaximized():
            self._drag_position = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_position is not None and event.buttons() & Qt.LeftButton and not self.window.isMaximized():
            self.window.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.window.toggle_maximize()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class Sidebar(QFrame):
    page_requested = Signal(int)

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window
        self.setObjectName("sidebar")
        self.expanded_width = 232
        self.collapsed_width = 76
        self.setMinimumWidth(self.expanded_width)
        self.setMaximumWidth(self.expanded_width)
        self.expanded = True
        self._animation: QPropertyAnimation | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 13, 11, 13)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.menu_button = QPushButton(window.t("menu"))
        self.menu_button.setObjectName("navButton")
        self.menu_button.setIcon(icon("menu.svg"))
        self.menu_button.setIconSize(QSize(19, 19))
        self.menu_button.clicked.connect(self.toggle)
        top.addWidget(self.menu_button)
        layout.addLayout(top)

        self.navigation_label = QLabel(window.t("navigation"))
        self.navigation_label.setObjectName("tiny")
        layout.addWidget(self.navigation_label)

        self.buttons: list[QPushButton] = []
        self.keys = ("home", "servers", "scanner", "settings", "about")
        items = (
            ("home", "home.svg"),
            ("servers", "servers.svg"),
            ("scanner", "search.svg"),
            ("settings", "settings.svg"),
            ("about", "info.svg"),
        )
        self.assets = tuple(asset for _, asset in items)
        for index, (key, asset) in enumerate(items):
            button = QPushButton(window.t(key))
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setIcon(icon(asset))
            button.setIconSize(QSize(19, 19))
            button.clicked.connect(partial(self._request_page, index))
            self.buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()

        self.status_card = QFrame()
        self.status_card.setObjectName("sidebarStatus")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)
        self.status_title = QLabel(window.t("connection_status"))
        self.status_title.setObjectName("tiny")
        self.status_value = QLabel(window.t("disconnected"))
        self.status_value.setObjectName("statusOffline")
        status_layout.addWidget(self.status_title)
        status_layout.addWidget(self.status_value)
        layout.addWidget(self.status_card)

        version = QLabel(f"dicodePing  v{__version__}")
        version.setObjectName("tiny")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        self.version_label = version

    def _request_page(self, index: int, _checked: bool = False) -> None:
        self.page_requested.emit(index)

    def set_current(self, index: int) -> None:
        for position, button in enumerate(self.buttons):
            selected = position == index
            button.setChecked(selected)
            button.setIcon(tinted_icon(self.assets[position]) if selected else icon(self.assets[position]))

    def set_connection_state(self, connected: bool, busy: bool = False) -> None:
        if busy:
            self.status_value.setText(self.window.t("processing"))
            self.status_value.setObjectName("statusBusy")
        elif connected:
            self.status_value.setText(self.window.t("connected"))
            self.status_value.setObjectName("statusOnline")
        else:
            self.status_value.setText(self.window.t("disconnected"))
            self.status_value.setObjectName("statusOffline")
        repolish(self.status_value)

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        if expanded == self.expanded and self.maximumWidth() in {self.expanded_width, self.collapsed_width}:
            return
        self.expanded = expanded
        target = self.expanded_width if expanded else self.collapsed_width
        for position, button in enumerate(self.buttons):
            button.setText(self.window.t(self.keys[position]) if expanded else "")
            button.setToolTip("" if expanded else self.window.t(self.keys[position]))
        self.menu_button.setText(self.window.t("menu") if expanded else "")
        self.navigation_label.setVisible(expanded)
        self.status_card.setVisible(expanded)
        self.version_label.setText(f"dicodePing  v{__version__}" if expanded else f"v{__version__}")
        if not animate:
            self.setMinimumWidth(target)
            self.setMaximumWidth(target)
            return
        animation = QPropertyAnimation(self, b"maximumWidth", self)
        animation.setDuration(135)
        animation.setStartValue(self.maximumWidth())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.valueChanged.connect(lambda value: self.setMinimumWidth(int(value)))
        self._animation = animation
        animation.start()

    def toggle(self) -> None:
        self.set_expanded(not self.expanded)


class ActivityBar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("activityBar")
        self.setMaximumHeight(0)
        self.setMinimumHeight(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(7)
        row = QHBoxLayout()
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.value = QLabel("")
        self.value.setObjectName("tiny")
        row.addWidget(self.label, 1)
        row.addWidget(self.value)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self._animation: QPropertyAnimation | None = None

    def _animate(self, end: int) -> None:
        animation = QPropertyAnimation(self, b"maximumHeight", self)
        animation.setDuration(120)
        animation.setStartValue(self.maximumHeight())
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.valueChanged.connect(lambda value: self.setMinimumHeight(int(value)))
        self._animation = animation
        animation.start()

    def show_activity(self, text: str) -> None:
        self.label.setText(text)
        self.value.setText("")
        self.progress.setRange(0, 0)
        self._animate(66)

    def set_stage(self, text: str) -> None:
        self.label.setText(text)

    def set_progress(self, current: int, total: int) -> None:
        total = max(1, total)
        current = min(max(0, current), total)
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        percent = int(round((current / total) * 100))
        self.value.setText(f"{percent}%")

    def hide_activity(self) -> None:
        self._animate(0)


class StaticSkeleton(QFrame):
    """Non-animated loading skeleton to avoid expensive paint timers."""

    def __init__(self, rows: int = 7) -> None:
        super().__init__()
        self.setObjectName("skeletonCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        for row_index in range(rows):
            row = QHBoxLayout()
            row.setSpacing(12)
            widths = (44, 170, 125, 105, 75) if row_index else (52, 210, 140, 110, 82)
            for width in widths:
                bar = QFrame()
                bar.setObjectName("skeletonBar")
                bar.setFixedHeight(14 if row_index else 16)
                bar.setMinimumWidth(width)
                bar.setMaximumWidth(width)
                row.addWidget(bar)
            row.addStretch()
            layout.addLayout(row)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        preloaded_servers: list[ServerRecord] | None = None,
        preloaded_settings: dict | None = None,
        startup_prepared: bool = False,
        startup_error: str = "",
    ) -> None:
        super().__init__()
        self.store = JsonStore()
        self.service = ServerService(self.store)
        self.manager = XrayManager()
        self.settings = dict(preloaded_settings) if preloaded_settings is not None else self.store.load_settings()
        self._startup_prepared = startup_prepared
        self._startup_error = startup_error
        self.language = "en" if self.settings.get("language") == "en" else "fa"
        self.is_rtl = self.language == "fa"
        self.sources: list[SourceDefinition] = normalize_sources(self.settings, self.language)
        self.settings["sources"] = serialize_sources(self.sources)
        self.settings.pop("custom_subscriptions", None)
        self.store.save_settings(self.settings)
        self.active_source_id = "all"
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if self.is_rtl else Qt.LeftToRight)
        self.setLayoutDirection(Qt.RightToLeft if self.is_rtl else Qt.LeftToRight)
        self.servers: list[ServerRecord] = list(preloaded_servers) if preloaded_servers is not None else self.store.load_servers()
        self.worker = None
        self.connection_monitor: ConnectionMonitorThread | None = None
        self._last_connected_ping: int | None = None
        self.connected_id = ""
        self._connecting_server_name = ""
        self._connect_dots = 0
        self._connect_button_timer = QTimer(self)
        self._connect_button_timer.setInterval(420)
        self._connect_button_timer.timeout.connect(self._animate_connect_button)
        self._is_closing = False
        self._sidebar_auto_collapsed = False
        self._busy_list_task = False
        self._restoring_server_selection = False

        self.setWindowTitle(f"dicodePing {__version__}")
        application_icon = QApplication.instance().windowIcon() if QApplication.instance() else QIcon()
        self.setWindowIcon(application_icon if not application_icon.isNull() else icon("app.png"))
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(840, 560)
        self.resize(1180, 760)

        self._build_ui()
        self.apply_theme(str(self.settings.get("theme", "dark")), save=False)
        self.render_subscription_list()
        self.render_servers()
        self.switch_page(0, animate=False)
        self.setWindowOpacity(0.0)
        self._show_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._show_animation.setDuration(155)
        self._show_animation.setStartValue(0.0)
        self._show_animation.setEndValue(1.0)
        self._show_animation.setEasingCurve(QEasingCurve.OutCubic)
        QTimer.singleShot(0, self._show_animation.start)
        QTimer.singleShot(450, self._after_start)

    def t(self, key: str, **kwargs) -> str:
        return tr(self.language, key, **kwargs)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("windowRoot")
        self.setCentralWidget(root)
        self.root_layout = QVBoxLayout(root)
        self.root_layout.setContentsMargins(8, 8, 8, 8)
        self.root_layout.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("appShell")
        self.root_layout.addWidget(self.shell)
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        shell_layout.addWidget(self.title_bar)

        body = QWidget()
        self.body_layout = QHBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.body_layout.setDirection(QBoxLayout.RightToLeft if self.is_rtl else QBoxLayout.LeftToRight)
        shell_layout.addWidget(body, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 20, 22, 14)
        content_layout.setSpacing(14)
        self.body_layout.addWidget(content, 1)

        self.activity_bar = ActivityBar()
        content_layout.addWidget(self.activity_bar)

        self.pages = FadeStackedWidget()
        for page in (
            self._build_home_page(),
            self._build_servers_page(),
            self._build_scanner_page(),
            self._build_settings_page(),
            self._build_about_page(),
        ):
            self.pages.addWidget(page)
        content_layout.addWidget(self.pages, 1)

        footer = QHBoxLayout()
        footer.setDirection(QBoxLayout.RightToLeft if self.is_rtl else QBoxLayout.LeftToRight)
        self.footer_state = QLabel(self.t("ready"))
        self.footer_state.setObjectName("tiny")
        footer.addWidget(self.footer_state)
        footer.addStretch()
        footer_note = QLabel(f"{self.t('tun_mode')}  •  {self.t('responsibility_short')}")
        footer_note.setObjectName("tiny")
        footer_note.setWordWrap(True)
        footer.addWidget(footer_note)
        grip = QSizeGrip(self)
        grip.setFixedSize(18, 18)
        footer.addWidget(grip)
        content_layout.addLayout(footer)

        self.sidebar = Sidebar(self)
        self.sidebar.page_requested.connect(self.switch_page)
        self.body_layout.addWidget(self.sidebar)

    def _page_header(self, title: str, subtitle: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("muted")
        subtitle_label.setWordWrap(True)
        subtitle_label.setMinimumHeight(24)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return container

    def _scrollable(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._page_header(self.t("home"), self.t("home_subtitle")))

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero.setMinimumHeight(250)
        self.hero_layout = QBoxLayout(QBoxLayout.LeftToRight, hero)
        self.hero_layout.setContentsMargins(22, 20, 22, 20)
        self.hero_layout.setSpacing(22)

        controls_widget = QWidget()
        controls = QVBoxLayout(controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        status_line = QHBoxLayout()
        status_line.setDirection(QBoxLayout.LeftToRight)
        self.home_status_dot = QFrame()
        self.home_status_dot.setObjectName("statusDot")
        self.home_status_dot.setProperty("status", "offline")
        self.home_status_dot.setFixedSize(10, 10)
        self.home_status_label = QLabel(self.t("disconnected"))
        self.home_status_label.setObjectName("statusOffline")
        status_line.addWidget(self.home_status_dot)
        status_line.addWidget(self.home_status_label)
        status_line.addStretch()
        controls.addLayout(status_line)
        self.home_hero_title = QLabel(self.t("simple_fast_ready"))
        self.home_hero_title.setObjectName("heroTitle")
        self.home_hero_title.setWordWrap(True)
        controls.addWidget(self.home_hero_title)
        self.home_hero_detail = QLabel(self.t("simple_fast_hint"))
        self.home_hero_detail.setObjectName("muted")
        self.home_hero_detail.setWordWrap(True)
        self.home_hero_detail.setMinimumHeight(46)
        controls.addWidget(self.home_hero_detail)
        controls.addStretch()
        self.home_primary_button = QPushButton(self.t("connect_best"))
        self.home_primary_button.setProperty("kind", "primary")
        self.home_primary_button.setIcon(tinted_icon("bolt.svg"))
        self.home_primary_button.setIconSize(QSize(18, 18))
        self.home_primary_button.clicked.connect(self.home_primary_action)
        controls.addWidget(self.home_primary_button)
        quick = QHBoxLayout()
        self.home_scan_button = QPushButton(self.t("update_servers"))
        self.home_scan_button.setIcon(icon("search.svg"))
        self.home_scan_button.clicked.connect(self.start_scan)
        self.home_refresh_button = QPushButton(self.t("refresh_ping"))
        self.home_refresh_button.setIcon(icon("refresh.svg"))
        self.home_refresh_button.clicked.connect(self.start_refresh)
        quick.addWidget(self.home_scan_button)
        quick.addWidget(self.home_refresh_button)
        controls.addLayout(quick)
        self.hero_layout.addWidget(controls_widget, 3)

        self.hero_divider = QFrame()
        self.hero_divider.setFrameShape(QFrame.VLine)
        self.hero_layout.addWidget(self.hero_divider)

        info_widget = QWidget()
        info = QVBoxLayout(info_widget)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(10)
        self.home_target_label = QLabel(self.t("selected_connection_server"))
        self.home_target_label.setObjectName("muted")
        info.addWidget(self.home_target_label)
        best_name_row = QHBoxLayout()
        best_name_row.setSpacing(10)
        self.home_best_flag = QLabel()
        self.home_best_flag.setObjectName("flagBadge")
        self.home_best_flag.setFixedSize(42, 30)
        self.home_best_flag.setAlignment(Qt.AlignCenter)
        self.home_best_flag.setVisible(False)
        best_name_row.addWidget(self.home_best_flag)
        self.home_best_name = QLabel(self.t("no_server_ready"))
        self.home_best_name.setObjectName("sectionTitle")
        self.home_best_name.setWordWrap(True)
        best_name_row.addWidget(self.home_best_name, 1)
        info.addLayout(best_name_row)
        self.home_best_meta = QLabel("—")
        self.home_best_meta.setObjectName("muted")
        self.home_best_meta.setWordWrap(True)
        self.home_best_meta.setMinimumHeight(42)
        info.addWidget(self.home_best_meta)
        info.addStretch()
        open_servers = QPushButton(self.t("open_all_servers"))
        open_servers.setProperty("kind", "ghost")
        open_servers.setIcon(icon("servers.svg"))
        open_servers.clicked.connect(lambda: self.switch_page(1))
        info.addWidget(open_servers)
        self.hero_layout.addWidget(info_widget, 2)
        layout.addWidget(hero)

        self.live_metrics_card = QFrame()
        self.live_metrics_card.setObjectName("card")
        metrics_layout = QHBoxLayout(self.live_metrics_card)
        metrics_layout.setContentsMargins(18, 14, 18, 14)
        metrics_layout.setSpacing(18)

        def add_live_metric(title: str) -> QLabel:
            box = QVBoxLayout()
            box.setSpacing(2)
            value = QLabel("0 B")
            value.setObjectName("statValue")
            caption = QLabel(title)
            caption.setObjectName("muted")
            box.addWidget(value)
            box.addWidget(caption)
            metrics_layout.addLayout(box, 1)
            return value

        self.live_download_value = add_live_metric(self.t("session_download"))
        self.live_upload_value = add_live_metric(self.t("session_upload"))
        self.live_ping_value = add_live_metric(self.t("connected_ping"))
        self.live_ping_value.setText("—")
        self.live_metrics_card.setVisible(False)
        layout.addWidget(self.live_metrics_card)

        self.stats_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.stats_layout.setSpacing(12)
        self.stat_total = self._stat_card(self.t("saved_servers"), "0", "servers.svg")
        self.stat_online = self._stat_card(self.t("responsive_servers"), "0", "check.svg")
        self.stat_ping = self._stat_card(self.t("best_ping"), "—", "speed.svg")
        for card in (self.stat_total[0], self.stat_online[0], self.stat_ping[0]):
            self.stats_layout.addWidget(card)
        layout.addLayout(self.stats_layout)

        recent_card = QFrame()
        recent_card.setObjectName("card")
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(16, 14, 16, 14)
        recent_layout.setSpacing(10)
        recent_header = QHBoxLayout()
        recent_header.addWidget(QLabel(self.t("best_servers")))
        recent_header.addStretch()
        recent_hint = QLabel(self.t("based_on_icmp"))
        recent_hint.setObjectName("tiny")
        recent_header.addWidget(recent_hint)
        recent_layout.addLayout(recent_header)
        self.home_table = QTableWidget(0, 3)
        self.home_table.setHorizontalHeaderLabels([self.t("server"), self.t("location"), self.t("ping")])
        self.home_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.home_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.home_table.setFocusPolicy(Qt.NoFocus)
        self.home_table.verticalHeader().setVisible(False)
        self.home_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.home_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.home_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.home_table.setMinimumHeight(185)
        recent_layout.addWidget(self.home_table)
        layout.addWidget(recent_card, 1)
        return self._scrollable(page)

    def _stat_card(self, title: str, value: str, asset: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("statCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        icon_label = QLabel()
        icon_label.setPixmap(icon(asset).pixmap(25, 25))
        layout.addWidget(icon_label)
        text = QVBoxLayout()
        text.setSpacing(2)
        value_label = QLabel(value)
        value_label.setObjectName("statValue")
        title_label = QLabel(title)
        title_label.setObjectName("muted")
        title_label.setWordWrap(True)
        text.addWidget(value_label)
        text.addWidget(title_label)
        layout.addLayout(text, 1)
        return card, value_label

    def _build_servers_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.server_header_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.server_header_layout.setSpacing(12)
        title_box = self._page_header(self.t("servers"), self.t("servers_subtitle"))
        self.server_header_layout.addWidget(title_box, 1)
        self.server_actions_layout = QHBoxLayout()
        self.server_actions_layout.setSpacing(8)
        self.manual_connect_button = QPushButton(self.t("connect_selected"))
        self.manual_connect_button.setProperty("kind", "primary")
        self.manual_connect_button.setIcon(tinted_icon("power.svg"))
        self.manual_connect_button.clicked.connect(self.connect_selected)
        self.server_best_button = QPushButton(self.t("connect_best"))
        self.server_best_button.setIcon(icon("bolt.svg"))
        self.server_best_button.clicked.connect(self.connect_best)
        self.server_refresh_button = QPushButton(self.t("refresh_ping"))
        self.server_refresh_button.setIcon(icon("refresh.svg"))
        self.server_refresh_button.clicked.connect(self.start_refresh)
        self.server_scan_button = QPushButton(self.t("update_servers"))
        self.server_scan_button.setIcon(icon("search.svg"))
        self.server_scan_button.clicked.connect(self.start_scan)
        self.server_actions_layout.addWidget(self.manual_connect_button)
        self.server_actions_layout.addWidget(self.server_best_button)
        self.server_actions_layout.addWidget(self.server_refresh_button)
        self.server_actions_layout.addWidget(self.server_scan_button)
        self.server_header_layout.addLayout(self.server_actions_layout)
        layout.addLayout(self.server_header_layout)

        source_panel = QFrame()
        source_panel.setObjectName("toolbarCard")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(12, 10, 12, 10)
        source_layout.setSpacing(9)
        source_top = QHBoxLayout()
        source_title = QLabel(self.t("source_groups"))
        source_title.setObjectName("muted")
        source_top.addWidget(source_title)
        source_top.addStretch()
        self.server_count_label = QLabel("0")
        self.server_count_label.setObjectName("muted")
        source_top.addWidget(self.server_count_label)
        source_layout.addLayout(source_top)
        self.source_tabs = QTabBar()
        self.source_tabs.setExpanding(False)
        self.source_tabs.setDrawBase(False)
        self.source_tabs.setUsesScrollButtons(True)
        self.source_tabs.currentChanged.connect(self._source_tab_changed)
        source_layout.addWidget(self.source_tabs)
        layout.addWidget(source_panel)

        toolbar = QFrame()
        toolbar.setObjectName("toolbarCard")
        toolbar_layout = QHBoxLayout(toolbar)
        self.server_toolbar_layout = toolbar_layout
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(10)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(self.t("search_placeholder"))
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setAlignment(Qt.AlignRight if self.is_rtl else Qt.AlignLeft)
        self.filter_edit.setLayoutDirection(Qt.RightToLeft if self.is_rtl else Qt.LeftToRight)
        # ``render_servers`` is extended by the release runtime layers.  On
        # PySide6 6.10, connecting a signal directly to that rebound method can
        # raise an internal ``im_func`` AttributeError during window creation.
        # Keep the Qt callback a plain function and resolve the current method
        # only when the filter actually changes.
        self.filter_edit.textChanged.connect(lambda _text: self.render_servers())
        toolbar_layout.addWidget(self.filter_edit, 1)
        self.filter_status_combo = QComboBox()
        self.filter_status_combo.addItem(self.t("filter_all"), "all")
        self.filter_status_combo.addItem(self.t("filter_responsive"), "online")
        self.filter_status_combo.addItem(self.t("filter_unverified"), "unverified")
        self.filter_status_combo.currentIndexChanged.connect(lambda _index: self.render_servers())
        toolbar_layout.addWidget(self.filter_status_combo)
        layout.addWidget(toolbar)

        self.server_stack = QStackedWidget()
        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        # 8 columns: country | server | location | ip | ping | quality | pin | action
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            self.t("country"),
            self.t("server"),
            self.t("location"),
            self.t("ip"),
            self.t("ping"),
            self.t("quality_label"),
            self.t("pin"),
            self.t("action"),
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._server_double_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_server_menu)
        self.table.itemSelectionChanged.connect(self._server_selection_changed)
        table_layout.addWidget(self.table)

        empty_page = QFrame()
        empty_page.setObjectName("card")
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(12)
        empty_icon = QLabel()
        empty_icon.setPixmap(icon("servers.svg").pixmap(52, 52))
        empty_layout.addWidget(empty_icon, alignment=Qt.AlignCenter)
        empty_title = QLabel(self.t("empty_servers"))
        empty_title.setObjectName("sectionTitle")
        empty_layout.addWidget(empty_title, alignment=Qt.AlignCenter)
        empty_text = QLabel(self.t("empty_servers_hint"))
        empty_text.setObjectName("muted")
        empty_text.setWordWrap(True)
        empty_text.setAlignment(Qt.AlignCenter)
        empty_text.setMinimumHeight(50)
        empty_layout.addWidget(empty_text, alignment=Qt.AlignCenter)
        self.empty_scan_button = QPushButton(self.t("start_update"))
        self.empty_scan_button.setProperty("kind", "primary")
        self.empty_scan_button.setIcon(tinted_icon("search.svg"))
        self.empty_scan_button.clicked.connect(self.start_scan)
        empty_layout.addWidget(self.empty_scan_button, alignment=Qt.AlignCenter)

        self.loading_skeleton = StaticSkeleton(8)
        self.server_stack.addWidget(table_page)
        self.server_stack.addWidget(empty_page)
        self.server_stack.addWidget(self.loading_skeleton)
        layout.addWidget(self.server_stack, 1)
        return page

    def _build_scanner_page(self) -> QWidget:
        """Staged one-click scanner page (v1.6.0-rc.3).

        Three-stage flow triggered by a single "Start scan" button:

          Stage 1 — Connect
            Pick the best server from the primary source and start a
            real TUN connection so the crawler can reach t.me.

          Stage 2 — Crawl + Probe
            Crawl the bundled Telegram channels in parallel.  When the
            crawl is done, tear down the TUN and real-probe every
            unique config in parallel.  The user can press "Stop and
            save" at any point during this stage.

          Stage 3 — Save
            Save the survivors as a new user source whose name the
            user typed before pressing Start.
        """
        from .workers import ScannerThread, VolumeFetchThread
        from .scanner import list_scanner_subs
        from .volume import VolumeAutoDisconnect

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = self._page_header(self.t("scanner"), self.t("scanner_subtitle"))
        layout.addWidget(header)

        # --- Primary action card -----------------------------------------
        action_card = QFrame()
        action_card.setObjectName("heroCard")
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(22, 20, 22, 20)
        action_layout.setSpacing(12)

        # v1.6.0-rc.4: stage preview — show the user exactly what the
        # single button will do, before they press it.  This replaces
        # the old "connect first, then scan" two-step instruction.
        preview_title = QLabel(self.t("scanner_preview_title"))
        preview_title.setObjectName("sectionTitle")
        action_layout.addWidget(preview_title)
        for i in range(1, 5):
            preview_line = QLabel(self.t(f"scanner_preview_{i}"))
            preview_line.setObjectName("muted")
            preview_line.setWordWrap(True)
            action_layout.addWidget(preview_line)
        preview_hint = QLabel(self.t("scanner_preview_hint"))
        preview_hint.setStyleSheet("color:#6D8EFF;font-weight:700;")
        preview_hint.setWordWrap(True)
        action_layout.addWidget(preview_hint)

        # Primary action row: Start / Stop + ETA badge.
        action_top = QHBoxLayout()
        action_top.setSpacing(10)
        self.scanner_run_button = QPushButton(self.t("scanner_start"))
        self.scanner_run_button.setProperty("kind", "primary")
        self.scanner_run_button.setIcon(tinted_icon("bolt.svg"))
        self.scanner_run_button.setIconSize(QSize(20, 20))
        self.scanner_run_button.setMinimumHeight(54)
        self.scanner_run_button.clicked.connect(self.start_scanner)
        action_top.addWidget(self.scanner_run_button, 1)

        self.scanner_stop_button = QPushButton(self.t("scanner_stop"))
        self.scanner_stop_button.setProperty("kind", "danger")
        self.scanner_stop_button.setIcon(icon("close.svg"))
        self.scanner_stop_button.setMinimumHeight(54)
        self.scanner_stop_button.setVisible(False)
        self.scanner_stop_button.clicked.connect(self.stop_scanner)
        action_top.addWidget(self.scanner_stop_button)
        action_layout.addLayout(action_top)

        # Optional custom sub name input.
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_label = QLabel(self.t("scanner_name_prompt"))
        name_label.setObjectName("muted")
        name_label.setMinimumWidth(110)
        name_row.addWidget(name_label)
        self.scanner_name_edit = QLineEdit()
        self.scanner_name_edit.setPlaceholderText(self.t("scanner_name_placeholder"))
        self.scanner_name_edit.setAlignment(Qt.AlignRight if self.is_rtl else Qt.AlignLeft)
        self.scanner_name_edit.setLayoutDirection(Qt.RightToLeft if self.is_rtl else Qt.LeftToRight)
        name_row.addWidget(self.scanner_name_edit, 1)
        action_layout.addLayout(name_row)

        # Stage indicator (3 dots / labels).
        stage_row = QHBoxLayout()
        stage_row.setSpacing(10)
        self.scanner_stage_labels: list[QLabel] = []
        for i in range(1, 4):
            dot = QLabel(f"  {i}  ")
            dot.setObjectName("scannerStageDot")
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet(
                "background:#1B2430;color:#8F9CAD;border-radius:10px;"
                "min-width:20px;max-width:20px;min-height:20px;max-height:20px;"
                "font-weight:700;"
            )
            stage_row.addWidget(dot)
            self.scanner_stage_labels.append(dot)
        stage_row.addStretch()
        # Live "alive count" badge.
        self.scanner_alive_label = QLabel("")
        self.scanner_alive_label.setObjectName("muted")
        self.scanner_alive_label.setStyleSheet(
            "background:#10271D;color:#4FD08A;border-radius:10px;"
            "padding:3px 10px;font-weight:700;"
        )
        self.scanner_alive_label.setVisible(False)
        stage_row.addWidget(self.scanner_alive_label)
        # ETA badge.
        self.scanner_eta_label = QLabel("")
        self.scanner_eta_label.setObjectName("muted")
        self.scanner_eta_label.setStyleSheet(
            "background:#19233E;color:#6D8EFF;border-radius:10px;"
            "padding:3px 10px;font-weight:700;"
        )
        self.scanner_eta_label.setVisible(False)
        stage_row.addWidget(self.scanner_eta_label)
        action_layout.addLayout(stage_row)

        # Status line.
        self.scanner_stage_label = QLabel(self.t("ready"))
        self.scanner_stage_label.setObjectName("muted")
        self.scanner_stage_label.setWordWrap(True)
        action_layout.addWidget(self.scanner_stage_label)

        # Slim progress bar.
        self.scanner_progress = QProgressBar()
        self.scanner_progress.setRange(0, 100)
        self.scanner_progress.setValue(0)
        self.scanner_progress.setTextVisible(False)
        self.scanner_progress.setFixedHeight(6)
        action_layout.addWidget(self.scanner_progress)

        # Result line (shown after scan completes).
        self.scanner_result_label = QLabel("")
        self.scanner_result_label.setObjectName("muted")
        self.scanner_result_label.setWordWrap(True)
        action_layout.addWidget(self.scanner_result_label)

        layout.addWidget(action_card)

        # --- Live scanner log (v1.7.0-rc.1) -----------------------------
        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 12, 14, 12)
        log_layout.setSpacing(8)
        log_top = QHBoxLayout()
        log_title = QLabel(self.t("scanner_log_title"))
        log_title.setObjectName("sectionTitle")
        log_top.addWidget(log_title)
        log_top.addStretch()
        self.scanner_clear_log_button = QPushButton(self.t("scanner_clear_log"))
        self.scanner_clear_log_button.setIcon(icon("close.svg"))
        self.scanner_clear_log_button.clicked.connect(self._clear_scanner_log)
        log_top.addWidget(self.scanner_clear_log_button)
        log_layout.addLayout(log_top)
        self.scanner_log_view = QPlainTextEdit()
        self.scanner_log_view.setReadOnly(True)
        self.scanner_log_view.setMaximumBlockCount(2000)
        self.scanner_log_view.setStyleSheet(
            "QPlainTextEdit { background:#0B0F15; color:#B8C4D6; border:1px solid #222D3B; "
            "border-radius:8px; font-family:'Cascadia Code','Consolas','Menlo',monospace; font-size:11px; }"
        )
        self.scanner_log_view.setPlaceholderText(self.t("scanner_log_empty"))
        self.scanner_log_view.setMinimumHeight(140)
        log_layout.addWidget(self.scanner_log_view)
        layout.addWidget(log_card, 1)

        # --- History card ------------------------------------------------
        result_card = QFrame()
        result_card.setObjectName("card")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(14, 12, 14, 12)
        result_layout.setSpacing(10)

        result_top = QHBoxLayout()
        result_title = QLabel(self.t("scanner_history"))
        result_title.setObjectName("sectionTitle")
        result_top.addWidget(result_title)
        result_top.addStretch()

        self.scanner_copy_all_button = QPushButton(self.t("scanner_copy_all"))
        self.scanner_copy_all_button.setIcon(icon("check.svg"))
        self.scanner_copy_all_button.clicked.connect(self.scanner_copy_all)
        result_top.addWidget(self.scanner_copy_all_button)

        self.scanner_copy_b64_button = QPushButton(self.t("scanner_copy_base64"))
        self.scanner_copy_b64_button.setIcon(icon("check.svg"))
        self.scanner_copy_b64_button.clicked.connect(lambda: self.scanner_copy_all(as_base64=True))
        result_top.addWidget(self.scanner_copy_b64_button)

        result_layout.addLayout(result_top)

        self.scanner_history_list = QListWidget()
        self.scanner_history_list.setAlternatingRowColors(True)
        self.scanner_history_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scanner_history_list.itemSelectionChanged.connect(self._scanner_selection_changed)
        result_layout.addWidget(self.scanner_history_list)

        layout.addWidget(result_card, 1)

        # State placeholders (set up early so __init__ can reference them).
        self.scanner_thread: ScannerThread | None = None
        self.scanner_latest_sub: str = ""
        self.scanner_volume_thread: VolumeFetchThread | None = None
        self._volume_auto_disconnect = VolumeAutoDisconnect(self._volume_auto_disconnect_fire)
        self._scanner_alive_count = 0

        self._refresh_scanner_history()
        return page

    def _set_scanner_stage_dot(self, stage_number: int) -> None:
        """Highlight the given stage dot (1, 2, or 3)."""
        for i, dot in enumerate(self.scanner_stage_labels, start=1):
            if i == stage_number:
                dot.setStyleSheet(
                    "background:#6D8EFF;color:#FFFFFF;border-radius:10px;"
                    "min-width:20px;max-width:20px;min-height:20px;max-height:20px;"
                    "font-weight:700;"
                )
            elif i < stage_number:
                dot.setStyleSheet(
                    "background:#10271D;color:#4FD08A;border-radius:10px;"
                    "min-width:20px;max-width:20px;min-height:20px;max-height:20px;"
                    "font-weight:700;"
                )
            else:
                dot.setStyleSheet(
                    "background:#1B2430;color:#8F9CAD;border-radius:10px;"
                    "min-width:20px;max-width:20px;min-height:20px;max-height:20px;"
                    "font-weight:700;"
                )

    def start_scanner(self) -> None:
        """Kick off the staged scan in the background."""
        from .workers import ScannerThread

        if self.scanner_thread is not None and self.scanner_thread.isRunning():
            return
        custom_name = self.scanner_name_edit.text().strip() if hasattr(self, "scanner_name_edit") else ""
        # Pull the per-channel limits from settings.
        rank1_limit = int(self.settings.get("scanner_rank1_limit", 3))
        rank2_limit = int(self.settings.get("scanner_rank2_limit", 3))
        # Toggle buttons: hide Start, show Stop.
        self.scanner_run_button.setVisible(False)
        self.scanner_stop_button.setVisible(True)
        self.scanner_progress.setRange(0, 100)
        self.scanner_progress.setValue(0)
        self.scanner_stage_label.setText(self.t("scanner_stage1"))
        self.scanner_result_label.setText("")
        self.scanner_eta_label.setVisible(True)
        self.scanner_eta_label.setText(self.t("eta_label", eta="—"))
        self.scanner_alive_label.setVisible(False)
        self._scanner_alive_count = 0
        self._set_scanner_stage_dot(1)

        # If we are already connected to a server, skip Stage 1.
        bootstrap_server_id = self.connected_id or None

        thread = ScannerThread(
            self.store,
            language=self.language,
            custom_name=custom_name or None,
            rank1_limit=rank1_limit,
            rank2_limit=rank2_limit,
            connect_callback=self._scanner_connect_bootstrap,
            disconnect_callback=self._scanner_disconnect_bootstrap,
            is_connected_callback=lambda: self.manager.connected,
            bootstrap_server_id=bootstrap_server_id,
        )
        self.scanner_thread = thread
        thread.stage.connect(self._scanner_stage_updated)
        thread.stage_change.connect(self._scanner_stage_changed)
        thread.progress.connect(self._scanner_progress_updated)
        thread.eta.connect(self._scanner_eta_updated)
        thread.alive_count.connect(self._scanner_alive_count_updated)
        thread.log_line.connect(self._scanner_log_line)
        thread.success.connect(self._scanner_succeeded)
        thread.failed.connect(self._scanner_failed)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def stop_scanner(self) -> None:
        """Ask the running scanner to stop at the next safe point."""
        if self.scanner_thread is not None and self.scanner_thread.isRunning():
            self.scanner_thread.requestStop()
            self.scanner_stop_button.setEnabled(False)
            self.scanner_stop_button.setText(self.t("busy_wait"))

    def _scanner_connect_bootstrap(self, server_id: str) -> None:
        """UI-thread callback: connect to the chosen bootstrap server."""
        try:
            self.connect_by_id(server_id)
        except Exception:
            LOGGER.exception("Scanner: bootstrap connect failed")

    def _scanner_disconnect_bootstrap(self) -> None:
        """UI-thread callback: tear down the bootstrap TUN connection."""
        try:
            if self.manager.connected:
                self.disconnect(show_message=False)
        except Exception:
            LOGGER.exception("Scanner: bootstrap disconnect failed")

    def _scanner_stage_updated(self, text: str) -> None:
        self.scanner_stage_label.setText(text)

    def _scanner_stage_changed(self, stage_number: int, _label: str) -> None:
        self._set_scanner_stage_dot(stage_number)
        if stage_number >= 2:
            self.scanner_alive_label.setVisible(True)
            self.scanner_alive_label.setText(
                self.t("scanner_alive_count", count=self._scanner_alive_count)
            )

    def _scanner_progress_updated(self, current: int, total: int) -> None:
        if total <= 0:
            self.scanner_progress.setRange(0, 0)
            return
        self.scanner_progress.setRange(0, 100)
        ratio = max(0.0, min(1.0, current / total))
        self.scanner_progress.setValue(int(round(ratio * 100)))
        # Live alive count: we approximate from the current progress by
        # polling the scanner thread's internal state via a custom
        # attribute.  For simplicity we just keep the last value set by
        # the scanner thread via the ``alive_count`` signal (if we add
        # one).  For now, leave the count alone — the success message
        # will give the final number.
        if self.scanner_alive_label.isVisible():
            self.scanner_alive_label.setText(
                self.t("scanner_alive_count", count=self._scanner_alive_count)
            )

    def _scanner_eta_updated(self, eta_text: str) -> None:
        self.scanner_eta_label.setText(self.t("eta_label", eta=eta_text))

    def _scanner_alive_count_updated(self, count: int) -> None:
        self._scanner_alive_count = count
        if self.scanner_alive_label.isVisible():
            self.scanner_alive_label.setText(self.t("scanner_alive_count", count=count))

    def _scanner_log_line(self, line: str) -> None:
        """Append a live log line to the scanner log panel."""
        if hasattr(self, "scanner_log_view"):
            self.scanner_log_view.appendPlainText(line)

    def _clear_scanner_log(self) -> None:
        if hasattr(self, "scanner_log_view"):
            self.scanner_log_view.clear()

    def _scanner_succeeded(self, result) -> None:
        self.scanner_run_button.setVisible(True)
        self.scanner_run_button.setEnabled(True)
        self.scanner_run_button.setText(self.t("scanner_start"))
        self.scanner_stop_button.setVisible(False)
        self.scanner_stop_button.setEnabled(True)
        self.scanner_stop_button.setText(self.t("scanner_stop"))
        self.scanner_progress.setRange(0, 100)
        self.scanner_progress.setValue(100)
        duration = getattr(result, "duration_seconds", 0.0)
        alive = len(getattr(result, "servers", []))
        total = getattr(result, "downloaded", 0)
        stopped_early = bool(getattr(result, "stopped_early", False))
        self.scanner_eta_label.setVisible(False)
        self.scanner_alive_label.setVisible(False)
        self._set_scanner_stage_dot(3)
        self.scanner_stage_label.setText(self.t("scanner_done"))
        if stopped_early:
            self.scanner_result_label.setText(
                self.t("scanner_stopped_early")
                + "  •  "
                + self.t("scanner_result", alive=alive, total=total, duration=f"{duration:.1f}")
            )
        else:
            self.scanner_result_label.setText(
                self.t("scanner_result", alive=alive, total=total, duration=f"{duration:.1f}")
            )
        self.scanner_latest_sub = getattr(result, "sub_name", "") or ""
        try:
            self.sources = normalize_sources(self.settings, self.language)
            self.settings["sources"] = serialize_sources(self.sources)
        except Exception:
            LOGGER.exception("Scanner: failed to re-normalise sources after scan")
        self._refresh_scanner_history()
        try:
            self.servers = self.store.load_servers()
            self.render_servers()
            self.render_subscription_list()
        except Exception:
            LOGGER.exception("Scanner: failed to refresh server list after scan")

    def _scanner_failed(self, message: str) -> None:
        self.scanner_run_button.setVisible(True)
        self.scanner_run_button.setEnabled(True)
        self.scanner_run_button.setText(self.t("scanner_start"))
        self.scanner_stop_button.setVisible(False)
        self.scanner_stop_button.setEnabled(True)
        self.scanner_stop_button.setText(self.t("scanner_stop"))
        self.scanner_progress.setRange(0, 100)
        self.scanner_progress.setValue(0)
        self.scanner_eta_label.setVisible(False)
        self.scanner_alive_label.setVisible(False)
        self.scanner_stage_label.setText(self.t("operation_failed"))
        self.scanner_result_label.setText(message)

    def _refresh_scanner_history(self) -> None:
        from .scanner import list_scanner_subs

        self.scanner_history_list.clear()
        rows = list_scanner_subs()
        if not rows:
            item = QListWidgetItem(self.t("scanner_empty_history"))
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.scanner_history_list.addItem(item)
            return
        for row in rows:
            alive = len(row.get("servers") or [])
            total = row.get("downloaded") or 0
            duration = row.get("duration_seconds") or 0.0
            name = row.get("name") or ""
            label = f"{name}  •  {alive} سرور  •  {duration:.1f}s"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, name)
            self.scanner_history_list.addItem(item)
        if self.scanner_history_list.count() > 0 and not self.scanner_history_list.currentItem():
            self.scanner_history_list.setCurrentRow(0)

    def _scanner_selection_changed(self) -> None:
        item = self.scanner_history_list.currentItem()
        if not item:
            self.scanner_latest_sub = ""
            return
        data = item.data(Qt.UserRole)
        self.scanner_latest_sub = str(data or "")

    def scanner_copy_all(self, *, as_base64: bool = False) -> None:
        from .scanner import copy_all_servers, export_subscription
        from PySide6.QtGui import QClipboard

        sub_name = self.scanner_latest_sub
        if not sub_name:
            return
        payload = export_subscription(sub_name, as_base64=as_base64) if as_base64 else copy_all_servers(sub_name)
        if not payload:
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(payload, QClipboard.Clipboard)
        self.scanner_result_label.setText(self.t("scanner_copy_done"))

    def _volume_auto_disconnect_fire(self) -> None:
        """Called by the volume auto-disconnect timer (no-op in v1.7.0-rc.1)."""
        pass

    def _build_settings_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        layout.addWidget(self._page_header(self.t("settings"), self.t("settings_subtitle")))

        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        tabs.tabBar().setUsesScrollButtons(True)
        tabs.tabBar().setElideMode(Qt.ElideRight)
        self.settings_tabs = tabs
        layout.addWidget(tabs, 1)

        def tab_page() -> tuple[QScrollArea, QVBoxLayout]:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(14, 14, 14, 14)
            page_layout.setSpacing(14)
            page_layout.addStretch(0)
            scroll = self._scrollable(page)
            return scroll, page_layout

        # Connection behavior tab
        connection_tab, connection_layout = tab_page()
        behavior = QFrame()
        behavior.setObjectName("settingCard")
        behavior_layout = QVBoxLayout(behavior)
        behavior_layout.setContentsMargins(18, 16, 18, 18)
        behavior_layout.setSpacing(12)
        behavior_layout.addWidget(self._section_label(self.t("connection_behavior")))
        mode_row = QHBoxLayout()
        self.settings_mode_row = mode_row
        mode_text = QVBoxLayout()
        mode_label = QLabel(self.t("connection_mode"))
        mode_label.setObjectName("muted")
        mode_help = QLabel(self.t("mode_auto_help"))
        mode_help.setObjectName("tiny")
        mode_help.setWordWrap(True)
        mode_help.setMinimumHeight(34)
        mode_text.addWidget(mode_label)
        mode_text.addWidget(mode_help)
        mode_row.addLayout(mode_text, 1)
        self.connection_mode_combo = QComboBox()
        self.connection_mode_combo.addItem(self.t("mode_auto"), "auto")
        self.connection_mode_combo.addItem(self.t("mode_manual"), "manual")
        mode = self.settings.get("connection_mode", "auto")
        self.connection_mode_combo.setCurrentIndex(max(0, self.connection_mode_combo.findData(mode)))
        self.connection_mode_combo.setMinimumWidth(160)
        self.connection_mode_combo.setMaximumWidth(280)
        mode_row.addWidget(self.connection_mode_combo)
        behavior_layout.addLayout(mode_row)
        self.auto_connect_checkbox = QCheckBox(self.t("auto_connect_after_update"))
        self.auto_connect_checkbox.setChecked(bool(self.settings.get("auto_connect", False)))
        self.auto_scan_checkbox = QCheckBox(self.t("auto_update_empty"))
        self.auto_scan_checkbox.setChecked(bool(self.settings.get("auto_scan_empty", True)))
        behavior_layout.addWidget(self.auto_connect_checkbox)
        behavior_layout.addWidget(self.auto_scan_checkbox)
        self.connection_mode_combo.currentIndexChanged.connect(
            lambda: self.auto_connect_checkbox.setEnabled(self.connection_mode_combo.currentData() == "auto")
        )
        self.auto_connect_checkbox.setEnabled(self.connection_mode_combo.currentData() == "auto")
        connection_layout.insertWidget(connection_layout.count() - 1, behavior)
        tabs.addTab(connection_tab, self.t("settings_tab_connection"))

        # Direct/bypass domains tab
        bypass_tab, bypass_layout = tab_page()
        bypass_card = QFrame()
        bypass_card.setObjectName("settingCard")
        bypass_card_layout = QVBoxLayout(bypass_card)
        bypass_card_layout.setContentsMargins(18, 16, 18, 18)
        bypass_card_layout.setSpacing(12)
        bypass_card_layout.addWidget(self._section_label(self.t("bypass_title")))
        bypass_help = QLabel(self.t("bypass_help"))
        bypass_help.setObjectName("muted")
        bypass_help.setWordWrap(True)
        bypass_help.setMinimumHeight(48)
        bypass_card_layout.addWidget(bypass_help)
        self.bypass_enabled_checkbox = QCheckBox(self.t("bypass_enabled"))
        self.bypass_enabled_checkbox.setChecked(bool(self.settings.get("bypass_enabled", True)))
        bypass_card_layout.addWidget(self.bypass_enabled_checkbox)
        self.bypass_domains_input = QPlainTextEdit()
        self.bypass_domains_input.setPlaceholderText(self.t("bypass_placeholder"))
        self.bypass_domains_input.setLayoutDirection(Qt.LeftToRight)
        self.bypass_domains_input.setPlainText("\n".join(normalize_bypass_domains(self.settings.get("bypass_domains", []))))
        self.bypass_domains_input.setEnabled(self.bypass_enabled_checkbox.isChecked())
        self.bypass_enabled_checkbox.toggled.connect(self.bypass_domains_input.setEnabled)
        bypass_card_layout.addWidget(self.bypass_domains_input)
        bypass_note = QLabel(self.t("bypass_note"))
        bypass_note.setObjectName("tiny")
        bypass_note.setWordWrap(True)
        bypass_card_layout.addWidget(bypass_note)
        bypass_layout.insertWidget(bypass_layout.count() - 1, bypass_card)
        tabs.addTab(bypass_tab, self.t("settings_tab_bypass"))

        # Sources tab
        sources_tab, sources_tab_layout = tab_page()
        sources = QFrame()
        sources.setObjectName("settingCard")
        sources_layout = QVBoxLayout(sources)
        sources_layout.setContentsMargins(18, 16, 18, 18)
        sources_layout.setSpacing(12)
        sources_layout.addWidget(self._section_label(self.t("sources")))
        source_help = QLabel(self.t("source_manager_help"))
        source_help.setObjectName("muted")
        source_help.setWordWrap(True)
        source_help.setMinimumHeight(42)
        sources_layout.addWidget(source_help)

        input_row = QHBoxLayout()
        self.source_input_row = input_row
        input_row.setSpacing(8)
        self.subscription_name_input = QLineEdit()
        self.subscription_name_input.setPlaceholderText(self.t("source_name_placeholder"))
        self.subscription_name_input.setAlignment(Qt.AlignRight if self.is_rtl else Qt.AlignLeft)
        self.subscription_name_input.setLayoutDirection(Qt.RightToLeft if self.is_rtl else Qt.LeftToRight)
        self.subscription_input = QLineEdit()
        self.subscription_input.setPlaceholderText(self.t("subscription_url"))
        self.subscription_input.setClearButtonEnabled(True)
        self.subscription_input.setAlignment(Qt.AlignRight if self.is_rtl else Qt.AlignLeft)
        self.subscription_input.setLayoutDirection(Qt.RightToLeft if self.is_rtl else Qt.LeftToRight)
        self.subscription_input.returnPressed.connect(self.add_subscription)
        add_button = QPushButton(self.t("add"))
        add_button.setProperty("kind", "primary")
        add_button.clicked.connect(self.add_subscription)
        input_row.addWidget(self.subscription_name_input, 1)
        input_row.addWidget(self.subscription_input, 3)
        input_row.addWidget(add_button)
        sources_layout.addLayout(input_row)

        self.source_manager_table = QTableWidget(0, 4)
        self.source_manager_table.setHorizontalHeaderLabels([
            self.t("enabled"), self.t("source_name"), self.t("subscription_address"), self.t("source_type")
        ])
        self.source_manager_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.source_manager_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.source_manager_table.verticalHeader().setVisible(False)
        self.source_manager_table.setAlternatingRowColors(True)
        self.source_manager_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        source_header = self.source_manager_table.horizontalHeader()
        source_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        source_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        source_header.setSectionResizeMode(2, QHeaderView.Stretch)
        source_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.source_manager_table.setMinimumHeight(280)
        sources_layout.addWidget(self.source_manager_table)

        source_actions = QHBoxLayout()
        self.source_up_button = QPushButton(self.t("move_up"))
        self.source_down_button = QPushButton(self.t("move_down"))
        self.remove_subscription_button = QPushButton(self.t("remove_selected"))
        self.remove_subscription_button.setProperty("kind", "danger")
        self.source_up_button.clicked.connect(lambda: self.move_subscription(-1))
        self.source_down_button.clicked.connect(lambda: self.move_subscription(1))
        self.remove_subscription_button.clicked.connect(self.remove_subscription)
        source_actions.addWidget(self.source_up_button)
        source_actions.addWidget(self.source_down_button)
        source_actions.addStretch()
        source_actions.addWidget(self.remove_subscription_button)
        sources_layout.addLayout(source_actions)
        sources_tab_layout.insertWidget(sources_tab_layout.count() - 1, sources)
        tabs.addTab(sources_tab, self.t("settings_tab_sources"))

        # Appearance tab
        appearance_tab, appearance_tab_layout = tab_page()
        appearance = QFrame()
        appearance.setObjectName("settingCard")
        appearance_layout = QVBoxLayout(appearance)
        appearance_layout.setContentsMargins(18, 16, 18, 18)
        appearance_layout.setSpacing(12)
        appearance_layout.addWidget(self._section_label(self.t("appearance_language")))
        appearance_row = QHBoxLayout()
        self.settings_appearance_row = appearance_row
        theme_box = QVBoxLayout()
        theme_label = QLabel(self.t("theme"))
        theme_label.setObjectName("muted")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.t("dark"), "dark")
        self.theme_combo.addItem(self.t("light"), "light")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.settings.get("theme", "dark"))))
        theme_box.addWidget(theme_label)
        theme_box.addWidget(self.theme_combo)
        language_box = QVBoxLayout()
        language_label = QLabel(self.t("language"))
        language_label.setObjectName("muted")
        self.language_combo = QComboBox()
        self.language_combo.addItem(self.t("persian"), "fa")
        self.language_combo.addItem(self.t("english"), "en")
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.language)))
        language_box.addWidget(language_label)
        language_box.addWidget(self.language_combo)
        appearance_row.addLayout(theme_box, 1)
        appearance_row.addLayout(language_box, 1)
        appearance_layout.addLayout(appearance_row)
        restart_note = QLabel(self.t("language_restart"))
        restart_note.setObjectName("tiny")
        restart_note.setWordWrap(True)
        appearance_layout.addWidget(restart_note)
        appearance_tab_layout.insertWidget(appearance_tab_layout.count() - 1, appearance)
        tabs.addTab(appearance_tab, self.t("settings_tab_appearance"))

        # Performance and diagnostics tab
        advanced_tab, advanced_layout = tab_page()
        advanced = QFrame()
        advanced.setObjectName("settingCard")
        advanced_form = QVBoxLayout(advanced)
        advanced_form.setContentsMargins(18, 16, 18, 18)
        advanced_form.setSpacing(12)
        advanced_form.addWidget(self._section_label(self.t("performance_diagnostics")))
        self.settings_advanced_rows = []

        def number_option(label_key: str, setting_key: str, minimum: int, maximum: int, default: int, suffix: str = "") -> QSpinBox:
            row = QHBoxLayout()
            self.settings_advanced_rows.append(row)
            label = QLabel(self.t(label_key))
            label.setObjectName("muted")
            label.setWordWrap(True)
            field = QSpinBox()
            field.setRange(minimum, maximum)
            field.setValue(int(self.settings.get(setting_key, default) or default))
            if suffix:
                field.setSuffix(suffix)
            field.setMinimumWidth(120)
            row.addWidget(label, 1)
            row.addWidget(field)
            advanced_form.addLayout(row)
            return field

        self.test_concurrency_spin = number_option("parallel_tests", "test_concurrency", 4, 32, 16)
        self.test_batch_spin = number_option("test_batch_size", "test_batch_size", 8, 96, 48)
        self.test_timeout_spin = number_option("test_timeout", "test_timeout_ms", 1500, 5000, 3000, " ms")
        self.auto_retry_spin = number_option("auto_retry_count", "auto_retry_limit", 2, 12, 8)
        self.retry_failed_checkbox = QCheckBox(self.t("retry_failed_tests"))
        self.retry_failed_checkbox.setChecked(bool(self.settings.get("retry_failed_tests", True)))
        advanced_form.addWidget(self.retry_failed_checkbox)
        self.diagnostic_logging_checkbox = QCheckBox(self.t("diagnostic_logging"))
        self.diagnostic_logging_checkbox.setChecked(bool(self.settings.get("diagnostic_logging", False)))
        advanced_form.addWidget(self.diagnostic_logging_checkbox)
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItem(self.t("log_normal"), "INFO")
        self.log_level_combo.addItem(self.t("log_detailed"), "DEBUG")
        self.log_level_combo.setCurrentIndex(max(0, self.log_level_combo.findData(self.settings.get("log_level", "INFO"))))
        self.log_level_combo.setEnabled(self.diagnostic_logging_checkbox.isChecked())
        self.diagnostic_logging_checkbox.toggled.connect(self.log_level_combo.setEnabled)
        advanced_form.addWidget(self.log_level_combo)
        log_path_title = QLabel(self.t("log_location"))
        log_path_title.setObjectName("muted")
        advanced_form.addWidget(log_path_title)
        self.log_path_label = QLabel(str(LOG_FILE))
        self.log_path_label.setObjectName("tiny")
        self.log_path_label.setWordWrap(True)
        self.log_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.log_path_label.setToolTip(str(LOG_FILE))
        advanced_form.addWidget(self.log_path_label)
        log_hint = QLabel(self.t("log_disabled_hint"))
        log_hint.setObjectName("tiny")
        log_hint.setWordWrap(True)
        advanced_form.addWidget(log_hint)
        open_logs = QPushButton(self.t("open_log_file"))
        open_logs.clicked.connect(self.open_log_location)
        advanced_form.addWidget(open_logs, alignment=Qt.AlignRight if self.is_rtl else Qt.AlignLeft)
        clear_logs = QPushButton(self.t("clear_logs"))
        clear_logs.clicked.connect(lambda: LOG_FILE.unlink(missing_ok=True))
        advanced_form.addWidget(clear_logs, alignment=Qt.AlignRight if self.is_rtl else Qt.AlignLeft)
        advanced_layout.insertWidget(advanced_layout.count() - 1, advanced)
        tabs.addTab(advanced_tab, self.t("settings_tab_advanced"))

        # Local data tab
        data_tab, data_tab_layout = tab_page()
        data_card = QFrame()
        data_card.setObjectName("settingCard")
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(18, 16, 18, 18)
        data_layout.setSpacing(12)
        data_layout.addWidget(self._section_label(self.t("local_data")))
        note = QLabel(self.t("local_data_help"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setMinimumHeight(44)
        data_layout.addWidget(note)
        clear_button = QPushButton(self.t("clear_servers"))
        clear_button.setProperty("kind", "danger")
        clear_button.clicked.connect(self.clear_servers)
        data_layout.addWidget(clear_button, alignment=Qt.AlignRight if self.is_rtl else Qt.AlignLeft)
        data_tab_layout.insertWidget(data_tab_layout.count() - 1, data_card)
        tabs.addTab(data_tab, self.t("settings_tab_data"))

        # --- Connection methods tab (v1.7.0-rc.1) ----------------------
        methods_tab = QWidget()
        methods_tab_layout = QVBoxLayout(methods_tab)
        methods_tab_layout.setContentsMargins(0, 0, 0, 0)
        methods_tab_layout.setSpacing(14)
        methods_tab_layout.addWidget(self._build_connection_methods_section())
        methods_tab_layout.addStretch()
        tabs.addTab(methods_tab, self.t("conn_method_title"))

        # --- VPN sharing tab (v1.7.0-rc.1) -----------------------------
        sharing_tab = QWidget()
        sharing_tab_layout = QVBoxLayout(sharing_tab)
        sharing_tab_layout.setContentsMargins(0, 0, 0, 0)
        sharing_tab_layout.setSpacing(14)
        sharing_tab_layout.addWidget(self._build_vpn_sharing_section())
        sharing_tab_layout.addStretch()
        tabs.addTab(sharing_tab, self.t("vpn_sharing_title"))

        actions = QHBoxLayout()
        self.settings_saved_label = QLabel("")
        self.settings_saved_label.setObjectName("statusOnline")
        actions.addWidget(self.settings_saved_label)
        actions.addStretch()
        save_button = QPushButton(self.t("save_settings"))
        save_button.setProperty("kind", "primary")
        save_button.clicked.connect(self.save_settings_page)
        actions.addWidget(save_button)
        layout.addLayout(actions)
        return content

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _build_connection_methods_section(self) -> QWidget:
        """Build the connection-methods settings section (v1.7.0-rc.1).

        Lets the user pick between Xray (default), Psiphon, and Aether.
        Alternative cores are downloaded on first use via the core
        manager.  CDN formatting is also configured here.
        """
        from .conn_methods import list_methods, get_method, is_default_method, DEFAULT_CDN_DOMAINS
        from .core_manager import is_core_available, get_active_core

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # --- Connection method selection ---
        method_card = QFrame()
        method_card.setObjectName("settingCard")
        method_layout = QVBoxLayout(method_card)
        method_layout.setContentsMargins(16, 14, 16, 14)
        method_layout.setSpacing(10)
        method_layout.addWidget(self._section_label(self.t("conn_method_title")))
        help_label = QLabel(self.t("conn_method_help"))
        help_label.setObjectName("muted")
        help_label.setWordWrap(True)
        method_layout.addWidget(help_label)

        self.conn_method_combo = QComboBox()
        active_core = get_active_core()
        for m in list_methods():
            label = m.name
            if m.id == active_core:
                label += f"  ({self.t('conn_method_active')})"
            elif m.requires_core_download and is_core_available(m.id):
                label += f"  ({self.t('conn_method_active')})"
            self.conn_method_combo.addItem(label, m.id)
        # Select the active method.
        for i in range(self.conn_method_combo.count()):
            if self.conn_method_combo.itemData(i) == active_core:
                self.conn_method_combo.setCurrentIndex(i)
                break
        method_layout.addWidget(self.conn_method_combo)

        # Download / activate button.
        button_row = QHBoxLayout()
        self.conn_method_download_button = QPushButton(self.t("conn_method_download"))
        self.conn_method_download_button.clicked.connect(self._download_selected_core)
        button_row.addWidget(self.conn_method_download_button)
        self.conn_method_activate_button = QPushButton(self.t("conn_method_activate"))
        self.conn_method_activate_button.setProperty("kind", "primary")
        self.conn_method_activate_button.clicked.connect(self._activate_selected_core)
        button_row.addWidget(self.conn_method_activate_button)
        button_row.addStretch()
        method_layout.addLayout(button_row)

        self.conn_method_status_label = QLabel("")
        self.conn_method_status_label.setObjectName("muted")
        self.conn_method_status_label.setWordWrap(True)
        method_layout.addWidget(self.conn_method_status_label)
        layout.addWidget(method_card)

        # --- CDN formatting ---
        cdn_card = QFrame()
        cdn_card.setObjectName("settingCard")
        cdn_layout = QVBoxLayout(cdn_card)
        cdn_layout.setContentsMargins(16, 14, 16, 14)
        cdn_layout.setSpacing(10)
        cdn_layout.addWidget(self._section_label(self.t("cdn_formatting_title")))
        cdn_help = QLabel(self.t("cdn_formatting_help"))
        cdn_help.setObjectName("muted")
        cdn_help.setWordWrap(True)
        cdn_layout.addWidget(cdn_help)
        self.cdn_enabled_checkbox = QCheckBox(self.t("cdn_formatting_enabled"))
        self.cdn_enabled_checkbox.setChecked(bool(self.settings.get("cdn_formatting_enabled", False)))
        cdn_layout.addWidget(self.cdn_enabled_checkbox)
        cdn_domain_row = QHBoxLayout()
        cdn_domain_label = QLabel(self.t("cdn_formatting_domain"))
        cdn_domain_label.setObjectName("muted")
        cdn_domain_label.setMinimumWidth(100)
        cdn_domain_row.addWidget(cdn_domain_label)
        self.cdn_domain_combo = QComboBox()
        self.cdn_domain_combo.setEditable(True)
        current_cdn = self.settings.get("cdn_formatting_domain", DEFAULT_CDN_DOMAINS[0])
        for domain in DEFAULT_CDN_DOMAINS:
            self.cdn_domain_combo.addItem(domain)
        self.cdn_domain_combo.setCurrentText(current_cdn)
        cdn_domain_row.addWidget(self.cdn_domain_combo, 1)
        cdn_layout.addLayout(cdn_domain_row)
        layout.addWidget(cdn_card)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_vpn_sharing_section(self) -> QWidget:
        """Build the VPN-sharing settings section (v1.7.0-rc.1)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("settingCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)
        card_layout.addWidget(self._section_label(self.t("vpn_sharing_title")))
        help_label = QLabel(self.t("vpn_sharing_help"))
        help_label.setObjectName("muted")
        help_label.setWordWrap(True)
        card_layout.addWidget(help_label)
        self.vpn_sharing_usb_checkbox = QCheckBox(self.t("vpn_sharing_usb"))
        self.vpn_sharing_usb_checkbox.setChecked(bool(self.settings.get("vpn_sharing_usb", False)))
        card_layout.addWidget(self.vpn_sharing_usb_checkbox)
        self.vpn_sharing_hotspot_checkbox = QCheckBox(self.t("vpn_sharing_hotspot"))
        self.vpn_sharing_hotspot_checkbox.setChecked(bool(self.settings.get("vpn_sharing_hotspot", False)))
        card_layout.addWidget(self.vpn_sharing_hotspot_checkbox)
        layout.addWidget(card)
        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _download_selected_core(self) -> None:
        """Download the core selected in the conn_method_combo."""
        from .core_manager import download_core, is_core_available, get_core
        core_id = self.conn_method_combo.currentData()
        if not core_id or core_id == "xray":
            self.conn_method_status_label.setText("Xray هسته پیش‌فرض است و نیازی به دانلود ندارد.")
            return
        if is_core_available(core_id):
            self.conn_method_status_label.setText(self.t("conn_method_download_done"))
            return
        self.conn_method_download_button.setEnabled(False)
        self.conn_method_download_button.setText(self.t("conn_method_downloading"))
        # Run the download in a background thread to avoid blocking the UI.
        from .workers import CoreDownloadThread
        self._core_download_thread = CoreDownloadThread(core_id, language=self.language)
        self._core_download_thread.stage.connect(
            lambda text: self.conn_method_status_label.setText(text)
        )
        self._core_download_thread.success.connect(self._on_core_download_success)
        self._core_download_thread.failed.connect(self._on_core_download_failed)
        self._core_download_thread.finished.connect(self._core_download_thread.deleteLater)
        self._core_download_thread.start()

    def _on_core_download_success(self, core_id: str) -> None:
        self.conn_method_download_button.setEnabled(True)
        self.conn_method_download_button.setText(self.t("conn_method_download"))
        self.conn_method_status_label.setText(self.t("conn_method_download_done"))

    def _on_core_download_failed(self, message: str) -> None:
        self.conn_method_download_button.setEnabled(True)
        self.conn_method_download_button.setText(self.t("conn_method_download"))
        self.conn_method_status_label.setText(self.t("conn_method_download_failed") + f": {message}")

    def _activate_selected_core(self) -> None:
        """Activate the core selected in the conn_method_combo."""
        from .core_manager import set_active_core, is_core_available
        core_id = self.conn_method_combo.currentData()
        if not core_id:
            return
        if core_id != "xray" and not is_core_available(core_id):
            self.conn_method_status_label.setText(
                "هسته دانلود نشده است. ابتدا روی «دانلود هسته» بزنید."
            )
            return
        try:
            set_active_core(core_id)
            self.conn_method_status_label.setText(self.t("conn_method_active") + f": {core_id}")
        except Exception as exc:
            self.conn_method_status_label.setText(f"خطا: {exc}")

    def _build_about_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        layout.addWidget(self._page_header(self.t("about"), self.t("about_subtitle")))

        intro = QFrame()
        intro.setObjectName("aboutCard")
        intro_layout = QHBoxLayout(intro)
        intro_layout.setContentsMargins(22, 20, 22, 20)
        logo = QLabel()
        logo.setPixmap(icon("app.svg").pixmap(72, 72))
        intro_layout.addWidget(logo)
        text = QVBoxLayout()
        name = QLabel(self.t("product"))
        name.setObjectName("heroTitle")
        desc = QLabel(self.t("about_desc"))
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        desc.setMinimumHeight(48)
        version = QLabel(f"dicodePing  •  v{__version__}  •  {self.t('built_by')} M_CODER")
        version.setObjectName("tiny")
        text.addWidget(name)
        text.addWidget(desc)
        text.addWidget(version)
        intro_layout.addLayout(text, 1)
        layout.addWidget(intro)

        links = QFrame()
        links.setObjectName("aboutCard")
        links_layout = QVBoxLayout(links)
        links_layout.setContentsMargins(18, 16, 18, 18)
        links_layout.setSpacing(10)
        links_layout.addWidget(self._section_label(self.t("official_links")))
        github_button = QPushButton("GitHub  •  github.com/mcodersir")
        github_button.setObjectName("linkButton")
        github_button.setIcon(icon("info.svg"))
        github_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/mcodersir/")))
        telegram_button = QPushButton(f"{self.t('official_channel')}  •  t.me/dicodeping")
        telegram_button.setObjectName("linkButton")
        telegram_button.setIcon(icon("servers.svg"))
        telegram_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://t.me/dicodeping")))
        links_layout.addWidget(github_button)
        links_layout.addWidget(telegram_button)
        logs_button = QPushButton(self.t("open_logs"))
        logs_button.setObjectName("linkButton")
        logs_button.setIcon(icon("info.svg"))
        logs_button.clicked.connect(self.open_log_location)
        links_layout.addWidget(logs_button)
        update_button = QPushButton("بررسی به‌روزرسانی" if self.language != "en" else "Check for updates")
        update_button.setObjectName("linkButton")
        update_button.setIcon(icon("refresh.svg"))
        update_button.clicked.connect(self.check_for_updates)
        links_layout.addWidget(update_button)
        layout.addWidget(links)

        privacy = QFrame()
        privacy.setObjectName("aboutCard")
        privacy_layout = QVBoxLayout(privacy)
        privacy_layout.setContentsMargins(18, 16, 18, 18)
        privacy_layout.setSpacing(10)
        privacy_layout.addWidget(self._section_label(self.t("privacy_connection")))
        for key in ("privacy_1", "privacy_2", "privacy_3", "privacy_4"):
            line = QHBoxLayout()
            mark = QLabel("•")
            mark.setObjectName("statusOnline")
            value = QLabel(self.t(key))
            value.setObjectName("muted")
            value.setWordWrap(True)
            value.setMinimumHeight(30)
            line.addWidget(mark)
            line.addWidget(value, 1)
            privacy_layout.addLayout(line)
        layout.addWidget(privacy)

        terms = QFrame()
        terms.setObjectName("aboutCard")
        terms_layout = QVBoxLayout(terms)
        terms_layout.setContentsMargins(18, 16, 18, 18)
        terms_layout.addWidget(self._section_label(self.t("terms")))
        message = QLabel(self.t("terms_text"))
        message.setObjectName("muted")
        message.setWordWrap(True)
        message.setMinimumHeight(60)
        terms_layout.addWidget(message)
        layout.addWidget(terms)
        layout.addStretch()
        return self._scrollable(content)

    def open_log_location(self) -> None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            message = (
                "ثبت گزارش عیب یابی اکنون خاموش است. آن را از تنظیمات فعال و ذخیره کنید.\n"
                if self.language != "en" else
                "Diagnostic logging is currently disabled. Enable and save it in Settings.\n"
            )
            LOG_FILE.write_text(message, encoding="utf-8")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE))):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE.parent)))

    def check_for_updates(self) -> None:
        if getattr(self, "_about_update_worker", None):
            return
        worker = ApplicationUpdateThread(self.settings, self.language)
        self._about_update_worker = worker

        def complete(source_data: object, release: object) -> None:
            self._about_update_worker = None
            changed, observed = source_data if isinstance(source_data, tuple) else ([], {})
            if observed and not self.settings.get("source_revisions"):
                self.settings["source_revisions"] = observed
                self.store.save_settings(self.settings)
            if release:
                answer = AppDialog.confirm(
                    self, self.t("about"),
                    (f"نسخه {release.tag} آماده است. صفحه دریافت باز شود؟" if self.language != "en" else f"Version {release.tag} is available. Open download page?"),
                    accept_text=("به‌روزرسانی" if self.language != "en" else "Update"), reject_text=self.t("later"),
                )
                if answer:
                    QDesktopServices.openUrl(QUrl(release.asset_url))
            elif changed:
                answer = AppDialog.confirm(
                    self, self.t("about"),
                    ("به‌روزرسانی ساب‌ها آماده است. اکنون دریافت شود؟" if self.language != "en" else "Server source updates are available. Download now?"),
                    accept_text=("به‌روزرسانی" if self.language != "en" else "Update"), reject_text=self.t("later"),
                )
                if answer:
                    self.settings["source_revisions"] = observed
                    self.store.save_settings(self.settings)
                    self.start_scan()
            else:
                AppDialog.info(self, self.t("about"), "برنامه و ساب‌ها به‌روز هستند." if self.language != "en" else "The app and sources are up to date.", self.t("ok"))

        worker.ready.connect(complete)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _after_start(self) -> None:
        if not self.settings.get("accepted_disclaimer"):
            accepted = AppDialog.confirm(
                self,
                self.t("terms"),
                self.t("terms_text"),
                accept_text=self.t("accept"),
                reject_text=self.t("exit"),
            )
            if not accepted:
                self._is_closing = True
                self.close()
                return
            self.settings["accepted_disclaimer"] = True
            self.store.save_settings(self.settings)
        if self._startup_error:
            LOGGER.warning("Startup preparation continued with cached data: %s", self._startup_error)
            self.footer_state.setText(self.t("ready"))
        # Download, ping, and location work is completed by the splash pipeline.
        # Do not repeat it after the main window becomes visible.

    def apply_theme(self, theme: str, *, save: bool = True) -> None:
        theme = "light" if theme == "light" else "dark"
        self.settings["theme"] = theme
        QApplication.instance().setStyleSheet(build_stylesheet(theme))
        if hasattr(self, "theme_combo"):
            index = self.theme_combo.findData(theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
        if save:
            self.store.save_settings(self.settings)

    def switch_page(self, index: int, _checked: bool = False, *, animate: bool = True) -> None:
        self.sidebar.set_current(index)
        if animate:
            self.pages.fade_to(index)
        else:
            self.pages.setCurrentIndex(index)

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            maximized = False
            self.root_layout.setContentsMargins(8, 8, 8, 8)
        else:
            self.showMaximized()
            maximized = True
            self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.shell.setProperty("maximized", maximized)
        repolish(self.shell)
        self.title_bar.set_maximized(maximized)

    def resizeEvent(self, event: QResizeEvent) -> None:
        width = event.size().width()
        if hasattr(self, "sidebar"):
            if width < 980 and self.sidebar.expanded:
                self.sidebar.set_expanded(False, animate=False)
                self._sidebar_auto_collapsed = True
            elif width >= 1040 and self._sidebar_auto_collapsed:
                self.sidebar.set_expanded(True, animate=False)
                self._sidebar_auto_collapsed = False
        if hasattr(self, "hero_layout"):
            narrow = width < 930
            self.hero_layout.setDirection(QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight)
            self.hero_divider.setVisible(not narrow)
            self.stats_layout.setDirection(QBoxLayout.TopToBottom if width < 800 else QBoxLayout.LeftToRight)
        if hasattr(self, "server_header_layout"):
            compact = width < 1080
            self.server_header_layout.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
        super().resizeEvent(event)

    def set_busy(self, busy: bool, stage: str = "") -> None:
        if busy:
            self.activity_bar.show_activity(stage or self.t("processing"))
            self.footer_state.setText(stage or self.t("processing"))
            if self._busy_list_task and hasattr(self, "server_stack"):
                self.server_stack.setCurrentIndex(2)
        else:
            self.activity_bar.hide_activity()
            self.footer_state.setText(stage or self.t("ready"))
            self._busy_list_task = False
        if hasattr(self, "sidebar"):
            self.sidebar.set_connection_state(self.manager.connected, busy)
        self._sync_action_states(busy)
        if stage:
            self._set_stage_text(stage)

    def _sync_action_states(self, busy: bool | None = None) -> None:
        busy = bool(self.worker) if busy is None else busy
        connecting = isinstance(self.worker, ConnectThread)
        has_servers = bool(self.servers)
        has_best = self.service.best_server(self.servers) is not None
        connected = self.manager.connected
        for button in (self.home_scan_button, self.server_scan_button, self.empty_scan_button):
            button.setEnabled(not busy)
        for button in (self.home_refresh_button, self.server_refresh_button):
            button.setEnabled(not busy and has_servers)
        self.server_best_button.setEnabled(not busy and has_best and not connected)
        self.table.setEnabled(not busy)
        self.filter_edit.setEnabled(not busy)
        self.filter_status_combo.setEnabled(not busy)
        self.source_tabs.setEnabled(not busy)
        selected = self.selected_server() if hasattr(self, "table") else None
        self.manual_connect_button.setEnabled(bool(selected) and not busy and not connected)
        manual = self.settings.get("connection_mode", "auto") == "manual"
        self.home_primary_button.setEnabled(connecting or (not busy and (connected or has_best or not has_servers or (manual and has_servers))))

    def _set_stage_text(self, text: str) -> None:
        self.activity_bar.set_stage(text)
        if self.manager.connected:
            self.home_hero_detail.setText(text)
        elif self.worker:
            self._set_status_visual("busy", self.t("processing"))
            self.home_hero_title.setText(self.t("processing"))
            self.home_hero_detail.setText(text)

    def bind_worker(self, worker) -> None:
        self.worker = worker
        worker.stage.connect(self._set_stage_text)
        worker.progress.connect(self.update_progress)
        worker.finished.connect(lambda worker=worker: self._worker_finished(worker))
        worker.start()

    def _worker_finished(self, finished_worker=None) -> None:
        from .rc8_core import is_current_worker

        # A delayed finished signal from an older task must not clear a newer
        # worker and re-enable controls in the middle of that task.
        if not is_current_worker(self.worker, finished_worker):
            return
        self.worker = None
        if not self.manager.connected:
            self._stop_connect_animation()
        self._set_scan_labels(False)
        self._sync_action_states(False)
        self.update_connection_ui()
        # Row action buttons are created while a worker exists and are therefore
        # disabled. Rebuild once after clearing the worker so they cannot remain
        # disabled after a successful discovery/refresh.
        if hasattr(self, "table") and self.servers:
            self.render_servers()

    def _start_connect_animation(self, server_name: str) -> None:
        self._connecting_server_name = server_name
        self._connect_dots = 0
        self._animate_connect_button()
        if not self._connect_button_timer.isActive():
            self._connect_button_timer.start()

    def _stop_connect_animation(self) -> None:
        self._connect_button_timer.stop()
        self._connecting_server_name = ""
        self._connect_dots = 0

    def _animate_connect_button(self) -> None:
        if not self._connecting_server_name or self.manager.connected:
            self._connect_button_timer.stop()
            return
        dots = "." * self._connect_dots
        self._connect_dots = (self._connect_dots + 1) % 4
        text = f"{self.t('cancel_connection')}{dots}"
        self.home_primary_button.setText(text)
        self.home_primary_button.setIcon(tinted_icon("refresh.svg"))
        self.home_primary_button.setProperty("kind", "primary")
        self.home_hero_title.setText(text)
        self.home_hero_detail.setText(self.t("connecting_to", name=self._connecting_server_name))
        self._set_status_visual("busy", self.t("processing"))
        repolish(self.home_primary_button)

    def _start_connection_monitor(self) -> None:
        self._stop_connection_monitor()
        self.live_download_value.setText("0 B")
        self.live_upload_value.setText("0 B")
        self.live_ping_value.setText("—")
        self._last_connected_ping = None
        self.live_metrics_card.setVisible(True)
        monitor = ConnectionMonitorThread(self.manager)
        monitor.updated.connect(self._connection_metrics_updated)
        self.connection_monitor = monitor
        monitor.start()

    def _stop_connection_monitor(self) -> None:
        monitor = self.connection_monitor
        self.connection_monitor = None
        if not monitor:
            return
        monitor.requestInterruption()
        if monitor.isRunning():
            monitor.wait(1500)
        monitor.deleteLater()

    def _connection_metrics_updated(self, payload: object) -> None:
        if not self.manager.connected or not isinstance(payload, dict):
            return
        upload = int(payload.get("upload") or 0)
        download = int(payload.get("download") or 0)
        ping = payload.get("ping")
        self.live_upload_value.setText(format_bytes(upload))
        self.live_download_value.setText(format_bytes(download))
        if isinstance(ping, int) and ping > 0:
            self.live_ping_value.setText(f"{ping} ms")
            if ping != self._last_connected_ping:
                self._last_connected_ping = ping
                server = next((item for item in self.servers if item.id == self.connected_id), None)
                if server:
                    server.ping_ms = ping
                    server.status = "online"
                for row in range(self.table.rowCount()):
                    name_item = self.table.item(row, 1)
                    if name_item and name_item.data(Qt.UserRole) == self.connected_id:
                        ping_item = self.table.item(row, 4)
                        if ping_item:
                            ping_item.setText(f"{ping} ms")
                            ping_item.setData(Qt.UserRole, ping)
                        break

    def _set_scan_labels(self, scanning: bool) -> None:
        text = self.t("getting_sources") if scanning else self.t("update_servers")
        self.home_scan_button.setText(text)
        self.server_scan_button.setText(text)
        self.empty_scan_button.setText(self.t("getting_sources") if scanning else self.t("start_update"))

    def update_progress(self, current: int, total: int) -> None:
        self.activity_bar.set_progress(current, total)

    def current_sources(self) -> list[SourceDefinition]:
        return [source for source in sorted(self.sources, key=lambda item: item.order) if source.enabled]

    def start_scan(self) -> None:
        if self.worker:
            return
        LOGGER.info("Manual server refresh requested")
        self.switch_page(1)
        self._busy_list_task = True
        self._set_scan_labels(True)
        self.set_busy(True, self.t("getting_sources"))
        worker = DiscoverThread(self.service, self.current_sources(), self.language)
        worker.preview_ready.connect(self.scan_preview_ready)
        worker.record_updated.connect(self.refresh_record_updated)
        worker.success.connect(self.scan_finished)
        worker.failed.connect(self.task_failed)
        self.bind_worker(worker)

    def scan_preview_ready(self, servers: object) -> None:
        """Replace the skeleton as soon as configs are parsed; enrichment continues in-place."""
        rows = list(servers) if isinstance(servers, (list, tuple)) else []
        if not rows:
            return
        self.servers = rows
        self._busy_list_task = False
        self.render_servers()

    def scan_finished(self, servers: object) -> None:
        self.servers = list(servers)
        self.settings["last_server_refresh_at"] = int(time.time())
        self.store.save_settings(self.settings)
        self._set_scan_labels(False)
        self.set_busy(False, self.t("update_done"))
        self.render_source_tabs()
        self.render_servers()
        if self.settings.get("connection_mode", "auto") == "auto" and self.settings.get("auto_connect"):
            QTimer.singleShot(220, self.connect_best)

    def start_refresh(self, auto: bool = False) -> None:
        if self.worker:
            return
        LOGGER.info("Server response and location refresh requested; auto=%s", auto)
        if not self.servers:
            self.start_scan()
            return
        # v1.6.0-rc.4: source-scoped refresh.  When the user has a
        # specific source tab active (not "all"), only re-ping that
        # source's servers.  This makes the ping button much faster on
        # a single-sub tab.
        if self.active_source_id and self.active_source_id != "all":
            target_ids = [s.id for s in self.servers if s.source_id == self.active_source_id]
            if target_ids:
                self._busy_list_task = False
                self.set_busy(True, self.t("refreshing_saved"))
                worker = RefreshSubsetThread(self.service, target_ids, self.language)
                worker.record_updated.connect(self.refresh_record_updated)
                worker.success.connect(lambda servers: self.refresh_finished(list(servers), auto))
                worker.failed.connect(self.task_failed)
                self.bind_worker(worker)
                return
        # Keep the current rows visible while their response times are updated.
        # Discovery still uses the skeleton, but a ping refresh is incremental.
        self._busy_list_task = False
        self.set_busy(True, self.t("refreshing_saved"))
        worker = RefreshThread(self.service, self.language)
        worker.record_updated.connect(self.refresh_record_updated)
        worker.success.connect(lambda servers: self.refresh_finished(list(servers), auto))
        worker.failed.connect(self.task_failed)
        self.bind_worker(worker)

    def refresh_record_updated(self, server: object) -> None:
        """Patch one visible row without resetting filtering or selection."""
        if not isinstance(server, ServerRecord):
            return
        for index, current in enumerate(self.servers):
            if current.id == server.id:
                self.servers[index] = server
                break
        else:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if not item or item.data(Qt.UserRole) != server.id:
                continue
            ping = self.table.item(row, 4)
            if ping:
                ping.setText(f"{server.ping_ms} ms" if server.ping_ms is not None else self.t("icmp_unavailable"))
                ping.setData(Qt.UserRole, server.ping_ms if server.ping_ms is not None else 999999)
            location = self.table.item(row, 2)
            if location:
                location.setText(self._server_location_text(server))
            address = self.table.item(row, 3)
            if address:
                address.setText(server.ip or server.host or "—")
            flag = self.table.cellWidget(row, 0)
            if isinstance(flag, QLabel):
                flag.setPixmap(country_flag_pixmap(server.country_code))
                flag.setToolTip(server.country or self.t("unknown"))
            break

    def refresh_finished(self, servers: list[ServerRecord], auto: bool) -> None:
        self.servers = servers
        self.set_busy(False, self.t("ping_updated"))
        self.render_servers()
        if not self.service.best_server(self.servers):
            # Manual mode can still use configs whose endpoints block ICMP.
            if self.settings.get("connection_mode", "auto") == "auto":
                answer = AppDialog.confirm(
                    self,
                    self.t("no_healthy_title"),
                    self.t("no_healthy_text"),
                    accept_text=self.t("retry_update"),
                    reject_text=self.t("later"),
                )
                if answer:
                    QTimer.singleShot(180, self.start_scan)
                    return
        if auto and self.settings.get("connection_mode", "auto") == "auto" and self.settings.get("auto_connect"):
            QTimer.singleShot(220, self.connect_best)

    def task_failed(self, message: str) -> None:
        self._set_scan_labels(False)
        self.set_busy(False, self.t("operation_failed"))
        self._set_status_visual("offline", self.t("disconnected"))
        self.home_hero_title.setText(self.t("operation_failed"))
        self.home_hero_detail.setText(message.splitlines()[0] if message else self.t("operation_failed"))
        AppDialog.error(self, self.t("error"), message, self.t("ok"))
        self.render_servers()

    def render_source_tabs(self) -> None:
        if not hasattr(self, "source_tabs"):
            return
        wanted = self.active_source_id
        self.source_tabs.blockSignals(True)
        while self.source_tabs.count():
            self.source_tabs.removeTab(0)
        all_index = self.source_tabs.addTab(self.t("all_sources"))
        self.source_tabs.setTabData(all_index, "all")
        source_counts: dict[str, int] = {}
        for server in self.servers:
            source_counts[server.source_id] = source_counts.get(server.source_id, 0) + 1
        for source in sorted(self.sources, key=lambda item: item.order):
            count = source_counts.get(source.id, 0)
            label = f"{source.name}  {count}" if count else source.name
            index = self.source_tabs.addTab(label)
            self.source_tabs.setTabData(index, source.id)
            self.source_tabs.setTabToolTip(index, source.url)
        selected_index = 0
        for index in range(self.source_tabs.count()):
            if self.source_tabs.tabData(index) == wanted:
                selected_index = index
                break
        self.source_tabs.setCurrentIndex(selected_index)
        self.active_source_id = str(self.source_tabs.tabData(selected_index) or "all")
        self.source_tabs.blockSignals(False)

    def _source_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        self.active_source_id = str(self.source_tabs.tabData(index) or "all")
        self.render_servers()

    def _filtered_servers(self) -> list[ServerRecord]:
        text = self.filter_edit.text().strip().casefold() if hasattr(self, "filter_edit") else ""
        status_filter = self.filter_status_combo.currentData() if hasattr(self, "filter_status_combo") else "all"
        result: list[ServerRecord] = []
        for server in self.servers:
            if self.active_source_id != "all" and server.source_id != self.active_source_id:
                continue
            if status_filter != "all" and server.status != status_filter:
                continue
            haystack = " ".join(
                (
                    server.name,
                    server.source_name,
                    server.country,
                    server.region,
                    server.city,
                    server.isp,
                    server.asn,
                    server.host,
                    server.ip,
                )
            ).casefold()
            if text and text not in haystack:
                continue
            result.append(server)
        result.sort(key=lambda item: (not item.favorite, item.ping_ms is None, item.ping_ms or 999999, item.name.casefold()))
        return result

    def _server_location_text(self, server: ServerRecord, *, include_country: bool = True) -> str:
        parts = []
        values = (server.city, server.region, server.country) if include_country else (server.city, server.region)
        for value in values:
            if value and value not in parts:
                parts.append(value)
        location = "، ".join(parts) if self.is_rtl else ", ".join(parts)
        return location or self.t("unknown")

    def _home_location_widget(self, server: ServerRecord) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(8)
        flag = QLabel()
        flag.setFixedSize(34, 24)
        flag.setPixmap(country_flag_pixmap(server.country_code))
        flag.setAlignment(Qt.AlignCenter)
        flag.setToolTip(server.country or self.t("unknown"))
        location = QLabel(self._server_location_text(server, include_country=False))
        location.setObjectName("muted")
        location.setToolTip(server.country or self.t("unknown"))
        row.addWidget(flag)
        row.addWidget(location, 1)
        return widget

    def render_servers(self) -> None:
        if not hasattr(self, "table"):
            return
        if self._busy_list_task:
            self.server_stack.setCurrentIndex(2)
            return
        current_item = self.table.item(self.table.currentRow(), 1) if self.table.currentRow() >= 0 else None
        selected_id = str(current_item.data(Qt.UserRole) if current_item else "") or str(
            self.settings.get("selected_server_id", "")
        )
        self.table.blockSignals(True)
        self.render_source_tabs()
        rows = self._filtered_servers()
        online = sum(1 for server in self.servers if server.status == "online" and server.ping_ms is not None)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row, server in enumerate(rows):
            flag = QLabel()
            flag.setObjectName("flagBadge")
            flag.setPixmap(country_flag_pixmap(server.country_code))
            flag.setAlignment(Qt.AlignCenter)
            flag.setToolTip(server.country or self.t("unknown"))
            self.table.setCellWidget(row, 0, flag)

            display_name = server.name
            name_item = QTableWidgetItem(display_name)
            name_item.setData(Qt.UserRole, server.id)
            name_item.setToolTip(f"{server.host}:{server.port}\n{server.isp}\n{server.asn}")
            self.table.setItem(row, 1, name_item)

            location_item = QTableWidgetItem(self._server_location_text(server))
            location_item.setToolTip(
                "\n".join(
                    part
                    for part in (
                        f"ISP: {server.isp}" if server.isp else "",
                        f"ASN: {server.asn}" if server.asn else "",
                        f"Provider: {server.geo_provider}" if server.geo_provider else "",
                        self.t("geo_estimate_note"),
                    )
                    if part
                )
            )
            self.table.setItem(row, 2, location_item)
            self.table.setItem(row, 3, QTableWidgetItem(server.ip or server.host or "—"))
            # Quality detection (v1.6.0): rate the ping latency into one of
            # four buckets and render the cell background accordingly.  The
            # bucket label is also exposed via the tooltip so screen readers
            # and hover-inspection still work.
            from .volume import rate_quality
            rating = rate_quality(server.ping_ms)
            ping_text = f"{server.ping_ms} ms" if server.ping_ms is not None else self.t("icmp_unavailable")
            ping_item = QTableWidgetItem(ping_text)
            ping_item.setTextAlignment(Qt.AlignCenter)
            ping_item.setData(Qt.UserRole, server.ping_ms if server.ping_ms is not None else 999999)
            # Color the ping cell based on the quality bucket.
            quality_color_map = {
                "excellent": DARK["successSoft"],
                "good": "#10271D",
                "fair": DARK["warning"] + "33",  # 20% alpha overlay tint
                "poor": DARK["dangerSoft"],
            }
            ping_brush = QBrush(QColor(quality_color_map.get(rating.bucket, "#1B2430")))
            ping_item.setBackground(ping_brush)
            volume_label = getattr(server, "_volume_label", None) or "—"
            ping_item.setToolTip(
                f"{self.t('scanner_quality_title')}: {rating.label_fa}\n"
                f"{self.t('scanner_volume_title')}: {volume_label}"
            )
            self.table.setItem(row, 4, ping_item)

            # Quality + volume info cell (v1.6.0-rc.3): show the bucket
            # word and the volume label inline, so the user does not need
            # to hover to see them.
            info_text = rating.label_fa
            if volume_label and volume_label != "—":
                info_text += f"\n{volume_label}"
            info_item = QTableWidgetItem(info_text)
            info_item.setTextAlignment(Qt.AlignCenter)
            # Match the ping cell colour so the row reads as a unit.
            info_item.setBackground(ping_brush)
            info_item.setToolTip(
                f"{self.t('scanner_quality_title')}: {rating.label_fa}\n"
                f"{self.t('scanner_volume_title')}: {volume_label}"
            )
            self.table.setItem(row, 5, info_item)

            pin_button = QPushButton()
            pin_button.setIcon(icon("pin-filled.svg" if server.favorite else "pin.svg"))
            pin_button.setIconSize(QSize(18, 18))
            pin_button.setObjectName("pinButton")
            pin_button.setToolTip(self.t("unpin_server") if server.favorite else self.t("pin_server"))
            pin_button.clicked.connect(lambda _=False, sid=server.id: self.toggle_favorite(sid))
            self.table.setCellWidget(row, 6, pin_button)

            restricted = self.service.is_restricted_location(server)
            if restricted:
                for disabled_item in (name_item, location_item, ping_item, info_item):
                    disabled_item.setFlags(disabled_item.flags() & ~Qt.ItemIsEnabled)
                flag.setEnabled(False)
                pin_button.setEnabled(False)
            connect = QPushButton(
                self.t("connected") if server.id == self.connected_id else
                (self.t("server_disabled") if restricted else self.t("connect"))
            )
            connect.setObjectName("tableAction")
            if server.id == self.connected_id:
                connect.setProperty("kind", "primary")
            # Manual connection is allowed even when ICMP is blocked.
            connect.setEnabled(not restricted and server.id != self.connected_id and not self.manager.connected and not self.worker)
            if restricted:
                connect.setToolTip(self.t("restricted_location_hint"))
            connect.clicked.connect(lambda _=False, sid=server.id: self.connect_by_id(sid))
            self.table.setCellWidget(row, 7, connect)
            self.table.setRowHeight(row, 64)
        if selected_id:
            self._restoring_server_selection = True
            try:
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 1)
                    if item and item.data(Qt.UserRole) == selected_id:
                        self.table.selectRow(row)
                        break
            finally:
                self._restoring_server_selection = False
        self.server_count_label.setText(self.t("shown_count", shown=len(rows), total=len(self.servers), online=online))
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self.server_stack.setCurrentIndex(0 if rows else 1)
        self._render_home_summary()
        self.update_connection_ui()
        self._update_manual_connect_state()
        self._sync_action_states()

    def _server_selection_changed(self) -> None:
        self._update_manual_connect_state()
        if self._restoring_server_selection:
            return
        server = self.selected_server()
        if not server:
            return
        self.settings["selected_server_id"] = server.id
        self.settings["connection_mode"] = "manual"
        if hasattr(self, "connection_mode_combo"):
            index = self.connection_mode_combo.findData("manual")
            if index >= 0 and self.connection_mode_combo.currentIndex() != index:
                self.connection_mode_combo.setCurrentIndex(index)
        self.store.save_settings(self.settings)
        self._render_home_summary()

    def _update_manual_connect_state(self) -> None:
        if not hasattr(self, "manual_connect_button"):
            return
        selected = self.selected_server()
        self.manual_connect_button.setEnabled(bool(selected) and not self.worker and not self.manager.connected)

    def _render_home_summary(self) -> None:
        online_rows = [server for server in self.servers if server.status == "online" and server.ping_ms is not None]
        online_rows.sort(key=lambda server: server.ping_ms or 999999)
        top = online_rows[:4]
        self.home_table.setRowCount(len(top))
        for row, server in enumerate(top):
            self.home_table.setItem(row, 0, QTableWidgetItem(server.name))
            self.home_table.setCellWidget(row, 1, self._home_location_widget(server))
            ping = QTableWidgetItem(f"{server.ping_ms} ms")
            ping.setTextAlignment(Qt.AlignCenter)
            self.home_table.setItem(row, 2, ping)
            self.home_table.setRowHeight(row, 46)
        self.stat_total[1].setText(str(len(self.servers)))
        self.stat_online[1].setText(str(len(online_rows)))
        best = self.service.best_server(self.servers)
        self.stat_ping[1].setText(f"{best.ping_ms} ms" if best and best.ping_ms is not None else "—")
        connected = next((server for server in self.servers if server.id == self.connected_id), None)
        selected = self.selected_server()
        manual = self.settings.get("connection_mode", "auto") == "manual"
        target = connected or (selected if manual else (best or selected or (self.servers[0] if self.servers else None)))
        if connected:
            self.home_target_label.setText(self.t("connected_server"))
        elif manual:
            self.home_target_label.setText(self.t("selected_connection_server"))
        else:
            self.home_target_label.setText(self.t("automatic_connection_server"))
        if target:
            self.home_best_flag.setPixmap(country_flag_pixmap(target.country_code, 38, 26))
            self.home_best_flag.setToolTip(target.country or self.t("unknown"))
            self.home_best_flag.setVisible(True)
            self.home_best_name.setText(target.name)
            latency = f"{target.ping_ms} ms" if target.ping_ms is not None else self.t("icmp_unavailable")
            self.home_best_meta.setText(
                f"{self._server_location_text(target, include_country=False)}  •  {target.ip or target.host}  •  {latency}"
            )
        else:
            self.home_best_flag.setVisible(False)
            self.home_best_name.setText(self.t("no_server_ready"))
            self.home_best_meta.setText(self.t("empty_servers_hint"))

    def toggle_favorite(self, server_id: str) -> None:
        target = next((item for item in self.servers if item.id == server_id), None)
        if not target:
            return
        if not target.favorite and sum(1 for item in self.servers if item.favorite) >= 6:
            AppDialog.info(self, self.t("pin_limit_title"), self.t("pin_limit_text"), self.t("ok"))
            return
        self.servers = self.service.toggle_favorite(server_id)
        self.render_servers()

    def rename_server(self, server_id: str) -> None:
        server = next((item for item in self.servers if item.id == server_id), None)
        if not server:
            return
        value, accepted = AppInputDialog.get_text(
            self, self.t("rename_server"), self.t("rename_server_hint"), server.name, self.t("save"), self.t("cancel")
        )
        if not accepted or not value or value == server.name:
            return
        for item in self.servers:
            if item.id == server_id:
                item.name = value[:80]
                try:
                    item.config_blob = config_to_blob(set_display_name(blob_to_config(item.config_blob), item.name))
                except Exception:
                    pass
                break
        self.store.save_servers(self.servers)
        self.render_servers()

    def _server_double_clicked(self, row: int, column: int) -> None:
        item = self.table.item(row, 1)
        server_id = item.data(Qt.UserRole) if item else ""
        if not server_id:
            return
        if column == 1:
            self.rename_server(server_id)
        else:
            self.connect_by_id(server_id)

    def _show_server_menu(self, position: QPoint) -> None:
        row = self.table.rowAt(position.y())
        if row < 0:
            return
        item = self.table.item(row, 1)
        server_id = item.data(Qt.UserRole) if item else ""
        server = next((entry for entry in self.servers if entry.id == server_id), None)
        if not server:
            return
        menu = QMenu(self)
        rename_action = menu.addAction(self.t("rename_server"))
        pin_action = menu.addAction(self.t("unpin_server") if server.favorite else self.t("pin_server"))
        connect_action = menu.addAction(self.t("connect"))
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen == rename_action:
            self.rename_server(server_id)
        elif chosen == pin_action:
            self.toggle_favorite(server_id)
        elif chosen == connect_action:
            self.connect_by_id(server_id)

    def selected_server(self) -> ServerRecord | None:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 1)
            server_id = item.data(Qt.UserRole) if item else ""
            selected = next((server for server in self.servers if server.id == server_id), None)
            if selected:
                return selected
        saved_id = str(self.settings.get("selected_server_id", ""))
        return next((server for server in self.servers if server.id == saved_id), None)

    def connect_selected(self) -> None:
        server = self.selected_server()
        if server:
            self.connect_server(server)

    def connect_by_id(self, server_id: str) -> None:
        server = next((item for item in self.servers if item.id == server_id), None)
        if server and not self.service.is_restricted_location(server):
            self.settings["selected_server_id"] = server.id
            self.settings["connection_mode"] = "manual"
            self.store.save_settings(self.settings)
            self.connect_server(server)

    def home_primary_action(self) -> None:
        if isinstance(self.worker, ConnectThread):
            self.worker.requestInterruption()
            self.manager.stop()
            self._stop_connect_animation()
            self.set_busy(False, self.t("connection_cancelled"))
            self.update_connection_ui()
            return
        if self.manager.connected:
            self.disconnect()
            return
        if not self.servers:
            self.start_scan()
            return
        if self.settings.get("connection_mode", "auto") == "manual":
            selected = self.selected_server()
            if selected:
                self.connect_server(selected)
            else:
                self.switch_page(1)
            return
        if self.service.best_server(self.servers):
            self.connect_best()
        else:
            self.start_refresh()

    def connect_best(self) -> None:
        server = self.service.best_server(self.servers)
        if server:
            self.connect_server(server)
        else:
            AppDialog.info(self, self.t("no_healthy_title"), self.t("need_refresh"), self.t("ok"))

    def connect_server(self, server: ServerRecord) -> None:
        if self.worker or self.manager.connected:
            return
        if self.service.is_restricted_location(server):
            AppDialog.info(self, self.t("server_disabled"), self.t("restricted_location_hint"), self.t("ok"))
            return
        LOGGER.info("Connection requested: id=%s host=%s port=%s", server.id, server.host, server.port)
        self.settings["selected_server_id"] = server.id
        self.store.save_settings(self.settings)
        bypass_domains = []
        if bool(self.settings.get("bypass_enabled", True)):
            bypass_domains = normalize_bypass_domains(self.settings.get("bypass_domains", []))
        self._start_connect_animation(server.name)
        self.set_busy(True, self.t("connecting_to", name=server.name))
        worker = ConnectThread(self.manager, server, self.language, bypass_domains=bypass_domains)
        worker.success.connect(self.connect_finished)
        worker.failed.connect(self.connect_failed)
        self.bind_worker(worker)

    def connect_finished(self, server: object) -> None:
        item: ServerRecord = server
        LOGGER.info("Connection verified: id=%s host=%s", item.id, item.host)
        self._stop_connect_animation()
        self.connected_id = item.id
        self.settings["last_server_id"] = item.id
        self.store.save_settings(self.settings)
        self.service.update_connected(item.id)
        self.set_busy(False, self.t("connected_to", name=item.name))
        self._start_connection_monitor()
        self.render_servers()
        self.update_connection_ui()

    def connect_failed(self, message: str) -> None:
        LOGGER.error("Connection failed: %s", message)
        self._stop_connect_animation()
        self._stop_connection_monitor()
        self.manager.stop()
        self.connected_id = ""
        self.live_metrics_card.setVisible(False)
        self.set_busy(False, self.t("connection_failed"))
        self.update_connection_ui()
        AppDialog.error(self, self.t("connection_error"), message, self.t("ok"))
        self.render_servers()

    def disconnect(self, *, show_message: bool = True) -> None:
        LOGGER.info("Disconnect requested")
        self._stop_connect_animation()
        self._stop_connection_monitor()
        self.manager.stop()
        self.connected_id = ""
        self.live_metrics_card.setVisible(False)
        self.live_download_value.setText("0 B")
        self.live_upload_value.setText("0 B")
        self.live_ping_value.setText("—")
        self.footer_state.setText(self.t("disconnected"))
        self.update_connection_ui()
        self.render_servers()
        if show_message:
            self.home_hero_detail.setText(self.t("disconnected"))

    def _set_status_visual(self, status: str, text: str) -> None:
        self.home_status_dot.setProperty("status", status)
        repolish(self.home_status_dot)
        self.home_status_label.setText(text)
        self.home_status_label.setObjectName({"online": "statusOnline", "offline": "statusOffline", "busy": "statusBusy"}.get(status, "statusOffline"))
        repolish(self.home_status_label)

    def update_connection_ui(self) -> None:
        connected = self.manager.connected
        manual = self.settings.get("connection_mode", "auto") == "manual"
        if connected:
            server = next((item for item in self.servers if item.id == self.connected_id), None)
            self.live_metrics_card.setVisible(True)
            self._set_status_visual("online", self.t("connected"))
            self.home_hero_title.setText(self.t("connected"))
            self.home_hero_detail.setText(self.t("traffic_via", name=server.name) if server else self.t("tun_active"))
            self.home_primary_button.setText(self.t("disconnect"))
            self.home_primary_button.setIcon(tinted_icon("power.svg"))
            self.home_primary_button.setProperty("kind", "danger")
        elif self.worker:
            self._set_status_visual("busy", self.t("processing"))
            self.home_primary_button.setText(
                self.t("connecting_button") if self._connecting_server_name else self.t("busy_wait")
            )
            self.home_primary_button.setIcon(tinted_icon("refresh.svg"))
            self.home_primary_button.setProperty("kind", "primary")
        else:
            self.live_metrics_card.setVisible(False)
            self._set_status_visual("offline", self.t("disconnected"))
            best = self.service.best_server(self.servers)
            if manual and self.servers:
                self.home_hero_title.setText(self.t("simple_fast_ready"))
                self.home_hero_detail.setText(self.t("manual_ready"))
                self.home_primary_button.setText(self.t("select_server"))
                self.home_primary_button.setIcon(tinted_icon("servers.svg"))
            elif best:
                self.home_hero_title.setText(self.t("simple_fast_ready"))
                self.home_hero_detail.setText(self.t("best_ready"))
                self.home_primary_button.setText(self.t("connect_best"))
                self.home_primary_button.setIcon(tinted_icon("bolt.svg"))
            elif self.servers:
                self.home_hero_title.setText(self.t("manual_only_ready"))
                self.home_hero_detail.setText(self.t("icmp_blocked_auto_hint"))
                self.home_primary_button.setText(self.t("refresh_ping"))
                self.home_primary_button.setIcon(tinted_icon("refresh.svg"))
            else:
                self.home_hero_title.setText(self.t("need_servers"))
                self.home_hero_detail.setText(self.t("list_empty"))
                self.home_primary_button.setText(self.t("update_servers"))
                self.home_primary_button.setIcon(tinted_icon("search.svg"))
            self.home_primary_button.setProperty("kind", "primary")
        if hasattr(self, "sidebar"):
            self.sidebar.set_connection_state(connected, bool(self.worker))
        repolish(self.home_primary_button)
        self._update_manual_connect_state()

    def render_subscription_list(self) -> None:
        if not hasattr(self, "source_manager_table"):
            return
        self.source_manager_table.setRowCount(len(self.sources))
        for row, source in enumerate(sorted(self.sources, key=lambda item: item.order)):
            enabled_item = QTableWidgetItem()
            enabled_item.setData(Qt.UserRole, source.id)
            enabled_item.setData(Qt.UserRole + 1, source.is_default)
            enabled_item.setCheckState(Qt.Checked if source.enabled else Qt.Unchecked)
            if source.is_default:
                enabled_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                enabled_item.setCheckState(Qt.Checked)
            else:
                enabled_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            self.source_manager_table.setItem(row, 0, enabled_item)

            name_item = QTableWidgetItem(source.name)
            name_item.setData(Qt.UserRole, source.id)
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            self.source_manager_table.setItem(row, 1, name_item)

            url_item = QTableWidgetItem(source.url)
            url_item.setToolTip(source.url)
            url_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.source_manager_table.setItem(row, 2, url_item)

            type_item = QTableWidgetItem(self.t("default_type") if source.is_default else self.t("custom_type"))
            type_item.setTextAlignment(Qt.AlignCenter)
            type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.source_manager_table.setItem(row, 3, type_item)
            self.source_manager_table.setRowHeight(row, 48)
        self.source_manager_table.resizeRowsToContents()

    def _sources_from_manager(self) -> list[SourceDefinition]:
        if not hasattr(self, "source_manager_table"):
            return list(self.sources)
        result: list[SourceDefinition] = []
        for row in range(self.source_manager_table.rowCount()):
            enabled_item = self.source_manager_table.item(row, 0)
            name_item = self.source_manager_table.item(row, 1)
            url_item = self.source_manager_table.item(row, 2)
            if not enabled_item or not name_item or not url_item:
                continue
            source_id = str(enabled_item.data(Qt.UserRole) or source_id_for_url(url_item.text()))
            is_default = bool(enabled_item.data(Qt.UserRole + 1)) or source_id == "default"
            name = name_item.text().strip() or (self.t("default_source_short") if is_default else self.t("source_fallback_name", number=row + 1))
            result.append(
                SourceDefinition(
                    id="default" if is_default else source_id,
                    name=name,
                    url=DEFAULT_SUBSCRIPTION_URL if is_default else url_item.text().strip(),
                    order=row,
                    enabled=True if is_default else enabled_item.checkState() == Qt.Checked,
                    is_default=is_default,
                )
            )
        return result or normalize_sources({}, self.language)

    def add_subscription(self) -> None:
        url = self.subscription_input.text().strip()
        name = self.subscription_name_input.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            AppDialog.error(self, self.t("error"), self.t("source_invalid"), self.t("ok"))
            return
        current = self._sources_from_manager()
        if any(source.url.casefold() == url.casefold() for source in current):
            AppDialog.info(self, self.t("sources"), self.t("source_duplicate"), self.t("ok"))
            return
        if sum(1 for source in current if not source.is_default) >= MAX_CUSTOM_SUBSCRIPTIONS:
            AppDialog.error(self, self.t("error"), self.t("source_limit"), self.t("ok"))
            return
        if not name:
            name = self.t("source_fallback_name", number=len(current) + 1)
        current.append(
            SourceDefinition(
                id=source_id_for_url(url),
                name=name,
                url=url,
                order=len(current),
                enabled=True,
                is_default=False,
            )
        )
        self.sources = current
        self.subscription_name_input.clear()
        self.subscription_input.clear()
        self.render_subscription_list()
        self.source_manager_table.selectRow(len(self.sources) - 1)

    def move_subscription(self, direction: int) -> None:
        row = self.source_manager_table.currentRow()
        if row < 0:
            AppDialog.info(self, self.t("sources"), self.t("select_source"), self.t("ok"))
            return
        current = self._sources_from_manager()
        target = row + direction
        if target < 0 or target >= len(current):
            return
        current[row], current[target] = current[target], current[row]
        for order, source in enumerate(current):
            source.order = order
        self.sources = current
        self.render_subscription_list()
        self.source_manager_table.selectRow(target)

    def remove_subscription(self) -> None:
        row = self.source_manager_table.currentRow()
        if row < 0:
            AppDialog.info(self, self.t("sources"), self.t("select_source"), self.t("ok"))
            return
        current = self._sources_from_manager()
        selected = current[row]
        if selected.is_default:
            AppDialog.info(self, self.t("sources"), self.t("default_source_locked"), self.t("ok"))
            return
        self.sources = [source for index, source in enumerate(current) if index != row]
        for order, source in enumerate(self.sources):
            source.order = order
        self.render_subscription_list()

    def save_settings_page(self) -> None:
        old_language = self.language
        self.sources = self._sources_from_manager()
        self.settings["sources"] = serialize_sources(self.sources)
        self.settings["auto_connect"] = self.auto_connect_checkbox.isChecked()
        self.settings["auto_scan_empty"] = self.auto_scan_checkbox.isChecked()
        self.settings["connection_mode"] = self.connection_mode_combo.currentData()
        bypass_domains = normalize_bypass_domains(self.bypass_domains_input.toPlainText())
        self.settings["bypass_enabled"] = self.bypass_enabled_checkbox.isChecked()
        self.settings["bypass_domains"] = bypass_domains
        self.bypass_domains_input.setPlainText("\n".join(bypass_domains))
        self.settings["language"] = self.language_combo.currentData()
        self.settings["test_concurrency"] = self.test_concurrency_spin.value()
        self.settings["test_batch_size"] = self.test_batch_spin.value()
        self.settings["test_timeout_ms"] = self.test_timeout_spin.value()
        self.settings["auto_retry_limit"] = self.auto_retry_spin.value()
        self.settings["retry_failed_tests"] = self.retry_failed_checkbox.isChecked()
        self.settings["diagnostic_logging"] = self.diagnostic_logging_checkbox.isChecked()
        self.settings["log_level"] = self.log_level_combo.currentData()
        # v1.7.0-rc.1: new settings.
        if hasattr(self, "cdn_enabled_checkbox"):
            self.settings["cdn_formatting_enabled"] = self.cdn_enabled_checkbox.isChecked()
            self.settings["cdn_formatting_domain"] = self.cdn_domain_combo.currentText().strip()
        if hasattr(self, "vpn_sharing_usb_checkbox"):
            self.settings["vpn_sharing_usb"] = self.vpn_sharing_usb_checkbox.isChecked()
            self.settings["vpn_sharing_hotspot"] = self.vpn_sharing_hotspot_checkbox.isChecked()
        selected_theme = str(self.theme_combo.currentData())
        self.apply_theme(selected_theme, save=False)

        source_map = {source.id: source for source in self.sources}
        for server in self.servers:
            source = source_map.get(server.source_id)
            if source:
                server.source_name = source.name
                server.source_order = source.order
        self.store.save_servers(self.servers)
        self.store.save_settings(self.settings)
        self.render_source_tabs()
        self.render_servers()
        self.settings_saved_label.setText(self.t("settings_saved"))
        QTimer.singleShot(2200, lambda: self.settings_saved_label.setText(""))
        self.update_connection_ui()
        if self.settings["language"] != old_language:
            AppDialog.info(self, self.t("restart_title"), self.t("language_restart"), self.t("ok"))

    def clear_servers(self) -> None:
        accepted = AppDialog.confirm(
            self,
            self.t("clear_title"),
            self.t("clear_confirm"),
            accept_text=self.t("delete"),
            reject_text=self.t("cancel"),
            danger=True,
        )
        if not accepted:
            return
        self.servers = []
        self.store.save_servers([])
        self.render_servers()
        self.switch_page(1)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._is_closing:
            self._stop_connection_monitor()
            self.manager.stop()
            event.accept()
            return
        if self.manager.connected:
            accepted = AppDialog.confirm(
                self,
                self.t("exit_title"),
                self.t("exit_confirm"),
                accept_text=self.t("exit_disconnect"),
                reject_text=self.t("stay"),
                danger=True,
            )
            if not accepted:
                event.ignore()
                return
        self._is_closing = True
        self._stop_connect_animation()
        self._stop_connection_monitor()
        self.manager.stop()
        event.accept()
