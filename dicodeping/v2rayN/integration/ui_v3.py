"""Modern PySide6 Qt UI for dicodePing Version 3.

Completely redesigned modern interface that uses the v2rayN-based
networking stack. Features a clean, card-based layout with
dark/light theme support and RTL language support.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Qt imports
if sys.version_info >= (3, 10):
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QStackedWidget, QFrame, QLabel, QPushButton, QSizePolicy,
        QSpacerItem, QStyle, QStyleOption, QStyleOptionButton,
        QStylePainter, QGraphicsDropShadowEffect,
        QTabWidget, QTabBar, QMdiArea,
    )
    from PySide6.QtCore import (
        Qt, QSize, QTimer, QEvent, QPropertyAnimation,
        QEasingCurve, QRect, QPoint, Signal, Property,
    )
    from PySide6.QtGui import (
        QFont, QFontDatabase, QPalette, QColor, QIcon,
        QPixmap, QPainter, QPen, QBrush, QAction,
    )
    from PySide6.QtGui import QGuiApplication, QCursor
else:
    from PySide2.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QStackedWidget, QFrame, QLabel, QPushButton, QSizePolicy,
        QSpacerItem, QStyle, QStyleOption, QStyleOptionButton,
        QStylePainter, QGraphicsDropShadowEffect,
        QTabWidget, QTabBar, QMdiArea,
    )
    from PySide2.QtCore import (
        Qt, QSize, QTimer, QEvent, QPropertyAnimation,
        QEasingCurve, QRect, QPoint, Signal, Property,
        QCoreApplication,
    )
    from PySide2.QtGui import (
        QFont, QFontDatabase, QPalette, QColor, QIcon,
        QPixmap, QPainter, QPen, QBrush, QAction,
    )
    from PySide2.QtGui import QGuiApplication, QCursor


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tokens:
    """Modern design tokens for the v2rayN UI."""

    # Colors
    background: str = "#0f1117"
    surface: str = "#1a1d24"
    surface_alt: str = "#22252d"
    surface_hover: str = "#2a2e37"
    border: str = "#2d3139"
    border_strong: str = "#3a3f4a"

    text_primary: str = "#e4e7ee"
    text_secondary: str = "#a0a5b1"
    text_disabled: str = "#6b7280"

    accent: str = "#5d8cff"
    accent_hover: str = "#7aa9ff"
    accent_strong: str = "#4a72e0"

    success: str = "#22c58e"
    success_hover: str = "#38d399"
    warning: str = "#f5a623"
    error: str = "#ff6b6b"
    error_hover: str = "#ff8e8e"

    online: str = "#22c58e"
    offline: str = "#6b7280"
    connecting: str = "#f5a623"

    # Spacing
    spacing_s: int = 4
    spacing_m: int = 8
    spacing_l: int = 16
    spacing_xl: int = 24
    spacing_xxl: int = 32

    # Typography
    font_family: str = "Vazirmatn, Inter, Segoe UI, system-ui, sans-serif"
    font_size_small: int = 11
    font_size_body: int = 12
    font_size_medium: int = 13
    font_size_large: int = 14
    font_size_xlarge: int = 16

    # Rounded corners
    radius_s: int = 4
    radius_m: int = 8
    radius_l: int = 12
    radius_xl: int = 16

    # Shadows
    shadow_sm: str = "0 1px 3px rgba(0, 0, 0, 0.30)"
    shadow: str = "0 4px 6px rgba(0, 0, 0, 0.35)"
    shadow_lg: str = "0 10px 15px rgba(0, 0, 0, 0.40)"
    shadow_xl: str = "0 20px 25px rgba(0, 0, 0, 0.50)"

    # Layout
    sidebar_width: int = 240
    header_height: int = 56
    footer_height: int = 48
    server_card_height: int = 64

    # Animations
    anim_fast: int = 150
    anim_normal: int = 250
    anim_slow: int = 400


tokens = Tokens()


# ---------------------------------------------------------------------------
# Theme management
# ---------------------------------------------------------------------------

class ThemeManager:
    """Manages dark/light themes with smooth transitions."""

    DARK = "dark"
    LIGHT = "light"

    def __init__(self, initial: str = DARK) -> None:
        self._current = initial
        self._tokens = tokens
        self._listeners: list[Callable[[str], None]] = []

    @property
    def current(self) -> str:
        return self._current

    @property
    def is_dark(self) -> bool:
        return self._current == self.DARK

    def get_tokens(self) -> Tokens:
        return self._tokens

    def toggle(self) -> str:
        self._current = self.LIGHT if self._current == self.DARK else self.DARK
        self._tokens = tokens  # Could add light tokens here
        for listener in self._listeners:
            listener(self._current)
        return self._current

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        callback(self._current)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def apply_palette(self, app: QApplication) -> None:
        """Apply the current theme to the QApplication."""
        palette = QPalette()
        if self.is_dark:
            palette.setColor(QPalette.Window, QColor(tokens.background))
            palette.setColor(QPalette.WindowText, QColor(tokens.text_primary))
            palette.setColor(QPalette.Base, QColor(tokens.surface))
            palette.setColor(QPalette.AlternateBase, QColor(tokens.surface_alt))
            palette.setColor(QPalette.ToolTipBase, QColor(tokens.surface_alt))
            palette.setColor(QPalette.ToolTipText, QColor(tokens.text_primary))
            palette.setColor(QPalette.Text, QColor(tokens.text_primary))
            palette.setColor(QPalette.Button, QColor(tokens.surface))
            palette.setColor(QPalette.ButtonText, QColor(tokens.text_primary))
            palette.setColor(QPalette.Highlight, QColor(tokens.accent))
            palette.setColor(QPalette.HighlightedText, QColor(tokens.text_primary))
        else:
            palette.setColor(QPalette.Window, QColor("#ffffff"))
            palette.setColor(QPalette.WindowText, QColor("#1a1a1a"))
            palette.setColor(QPalette.Base, QColor("#f8f9fa"))
            palette.setColor(QPalette.AlternateBase, QColor("#e9ecee"))
            palette.setColor(QPalette.ToolTipBase, QColor("#f8f9fa"))
            palette.setColor(QPalette.ToolTipText, QColor("#1a1a1a"))
            palette.setColor(QPalette.Text, QColor("#1a1a1a"))
            palette.setColor(QPalette.Button, QColor("#f8f9fa"))
            palette.setColor(QPalette.ButtonText, QColor("#1a1a1a"))
            palette.setColor(QPalette.Highlight, QColor("#4a72e0"))
            palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)


theme_manager = ThemeManager()


# ---------------------------------------------------------------------------
# Widget style helpers
# ---------------------------------------------------------------------------

class WidgetStyle:
    """Helper for applying modern styles to widgets."""

    @staticmethod
    def apply_card_style(widget: QWidget) -> None:
        """Apply a modern card-style background to a widget."""
        color = tokens.surface if theme_manager.is_dark else "#ffffff"
        border = tokens.border if theme_manager.is_dark else "#e9ecee"
        shadow = tokens.shadow if theme_manager.is_dark else "0 1px 3px rgba(0, 0, 0, 0.08)"
        widget.setStyleSheet(f"""
            background: {color};
            border: 1px solid {border};
            border-radius: {tokens.radius_m}px;
            box-shadow: {shadow};
        """)

    @staticmethod
    def apply_button_style(button: QPushButton, variant: str = "primary") -> None:
        """Apply a modern button style."""
        if variant == "primary":
            bg = tokens.accent
            hover_bg = tokens.accent_hover
            text_color = "#ffffff"
        elif variant == "success":
            bg = tokens.success
            hover_bg = tokens.success_hover
            text_color = "#ffffff"
        elif variant == "danger":
            bg = tokens.error
            hover_bg = tokens.error_hover
            text_color = "#ffffff"
        elif variant == "ghost":
            bg = "transparent"
            hover_bg = tokens.surface_hover
            text_color = tokens.text_secondary if theme_manager.is_dark else "#495057"
        else:
            bg = tokens.surface_alt
            hover_bg = tokens.surface_hover
            text_color = tokens.text_primary

        button.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {text_color};
                border: none;
                border-radius: {tokens.radius_m}px;
                padding: 8px 16px;
                font-family: {tokens.font_family};
                font-size: {tokens.font_size_body}px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
            QPushButton:pressed {{
                background: {tokens.accent}aa;
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)

    @staticmethod
    def apply_progress_style(progress) -> None:
        """Apply a modern progress bar style."""
        bar_color = tokens.accent
        bg_color = tokens.surface_alt if theme_manager.is_dark else "#e9ecee"
        text_color = tokens.text_primary if theme_manager.is_dark else "#1a1a1a"
        progress.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                background: {bg_color};
                border-radius: {tokens.radius_s}px;
                height: 8px;
                text-align: center;
                color: {text_color};
                font-size: {tokens.font_size_small}px;
            }}
            QProgressBar::chunk {{
                background: {bar_color};
                border-radius: {tokens.radius_s}px;
            }}
        """)

    @staticmethod
    def apply_card_shadow(widget: QWidget) -> None:
        """Apply a soft drop shadow to a widget."""
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(12)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 40 if theme_manager.is_dark else 10))
        widget.setGraphicsEffect(shadow)


# ---------------------------------------------------------------------------
# Modern widgets
# ---------------------------------------------------------------------------

class Card(QFrame):
    """A modern card-style container with subtle shadow and rounded corners."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        WidgetStyle.apply_card_style(self)
        WidgetStyle.apply_card_shadow(self)

    def resizeEvent(self, event) -> None:
        # Keep shadow smooth on resize
        WidgetStyle.apply_card_shadow(self)
        super().resizeEvent(event)


class FlatButton(QPushButton):
    """A flat button with modern styling."""

    def __init__(self, text: str = "", variant: str = "ghost", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self._variant = variant
        WidgetStyle.apply_button_style(self, variant)

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        WidgetStyle.apply_button_style(self, variant)


class AccentButton(QPushButton):
    """A prominent accent-colored button for primary actions."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        WidgetStyle.apply_button_style(self, "primary")


class StatusBar(QFrame):
    """A modern status bar showing connection state."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = "disconnected"
        self._status_label = QLabel("آماده به‌اتصال")
        self._ping_label = QLabel("—")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.spacing_m * 2, tokens.spacing_s, tokens.spacing_m * 2, tokens.spacing_s)

        # Status indicator
        self._indicator = QLabel()
        self._indicator.setFixedSize(10, 10)
        self._update_indicator("disconnected")

        # Status text
        self._status_label.setStyleSheet(f"""
            color: {tokens.text_secondary};
            font-size: {tokens.font_size_body}px;
        """)

        # Ping indicator
        self._ping_label.setStyleSheet(f"""
            color: {tokens.text_secondary};
            font-size: {tokens.font_size_body}px;
            font-weight: 500;
        """)

        layout.addWidget(self._indicator)
        layout.addSpacing(tokens.spacing_s)
        layout.addWidget(self._status_label)
        layout.addStretch()
        layout.addWidget(self._ping_label)

    def _update_indicator(self, state: str) -> None:
        colors = {
            "connected": tokens.success,
            "connecting": tokens.connecting,
            "disconnected": tokens.offline,
        }
        color = colors.get(state, tokens.offline)
        self._indicator.setStyleSheet(f"""
            background: {color};
            border-radius: 5px;
        """)

    def set_state(self, state: str, ping_ms: int | None = None) -> None:
        """Update the status bar with a new connection state."""
        self._state = state
        self._update_indicator(state)

        texts = {
            "connected": "متصل" if theme_manager.is_dark else "Connected",
            "connecting": "در حال اتصال…" if theme_manager.is_dark else "Connecting…",
            "disconnected": "قطع شده" if theme_manager.is_dark else "Disconnected",
        }
        text = texts.get(state, state)
        self._status_label.setText(text)

        if ping_ms is not None:
            self._ping_label.setText(f"{ping_ms}ms")
        else:
            self._ping_label.setText("—")

    def set_message(self, message: str) -> None:
        """Set a custom message in the status bar."""
        self._status_label.setText(message)


# ---------------------------------------------------------------------------
# Server card
# ---------------------------------------------------------------------------

class ServerCard(QFrame):
    """A modern server list card with latency, location, and status."""

    def __init__(
        self,
        name: str = "",
        protocol: str = "",
        ping_ms: int | None = None,
        country: str = "",
        country_code: str = "",
        status: str = "unknown",
        favorite: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._protocol = protocol
        self._ping_ms = ping_ms
        self._country = country
        self._country_code = country_code
        self._status = status
        self._favorite = favorite
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.spacing_m, tokens.spacing_s, tokens.spacing_m, tokens.spacing_s)
        layout.setSpacing(tokens.spacing_m)

        # Status indicator
        self._indicator = QLabel()
        self._indicator.setFixedSize(12, 12)
        self._update_status_indicator()

        # Content area
        content_layout = QVBoxLayout()
        content_layout.setSpacing(tokens.spacing_s)

        # Top row: name + protocol
        top_layout = QHBoxLayout()
        self._name_label = QLabel(self._name)
        self._name_label.setStyleSheet(f"""
            font-size: {tokens.font_size_medium}px;
            font-weight: 600;
            color: {tokens.text_primary};
        """)

        self._protocol_label = QLabel(self._protocol.upper() if self._protocol else "")
        self._protocol_label.setStyleSheet(f"""
            font-size: {tokens.font_size_small}px;
            color: {tokens.text_secondary};
            background: {tokens.surface_alt};
            border-radius: {tokens.radius_s}px;
            padding: 2px 6px;
        """)
        self._protocol_label.setMinimumHeight(20)

        top_layout.addWidget(self._name_label)
        top_layout.addWidget(self._protocol_label)
        top_layout.addStretch()

        # Bottom row: location + ping
        bottom_layout = QHBoxLayout()
        self._location_label = QLabel(f"{self._country} ({self._country_code})")
        self._location_label.setStyleSheet(f"""
            font-size: {tokens.font_size_small}px;
            color: {tokens.text_secondary};
        """)

        self._ping_label = QLabel(self._format_ping())
        self._ping_label.setStyleSheet(self._ping_style())

        bottom_layout.addWidget(self._location_label)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self._ping_label)

        content_layout.addLayout(top_layout)
        content_layout.addLayout(bottom_layout)

        # Favorite star
        self._star_label = QLabel("★" if self._favorite else "☆")
        self._star_label.setStyleSheet(f"""
            font-size: {tokens.font_size_large}px;
            color: {tokens.accent if self._favorite else tokens.text_disabled};
        """)

        layout.addWidget(self._indicator)
        layout.addLayout(content_layout)
        layout.addWidget(self._star_label)

        Card.apply_style(self)

    def _format_ping(self) -> str:
        if self._ping_ms is None:
            return "—"
        return f"{self._ping_ms}ms"

    def _ping_style(self) -> str:
        color = tokens.success if self._ping_ms is not None and self._ping_ms < 100 else (
            tokens.warning if self._ping_ms is not None and self._ping_ms < 300 else tokens.error
        )
        return f"""
            font-size: {tokens.font_size_medium}px;
            font-weight: 600;
            color: {color};
        """

    def _update_status_indicator(self) -> None:
        colors = {
            "online": tokens.success,
            "connecting": tokens.connecting,
            "unverified": tokens.offline,
            "unknown": tokens.offline,
        }
        color = colors.get(self._status, tokens.offline)
        self._indicator.setStyleSheet(f"""
            background: {color};
            border-radius: 6px;
        """)

    def update_data(self, **kwargs) -> None:
        """Update server card data."""
        if "name" in kwargs:
            self._name = kwargs["name"]
            self._name_label.setText(self._name)
        if "ping_ms" in kwargs:
            self._ping_ms = kwargs["ping_ms"]
            self._ping_label.setText(self._format_ping())
            self._ping_label.setStyleSheet(self._ping_style())
        if "status" in kwargs:
            self._status = kwargs["status"]
            self._update_status_indicator()
        if "favorite" in kwargs:
            self._favorite = kwargs["favorite"]
            self._star_label.setText("★" if self._favorite else "☆")
            self._star_label.setStyleSheet(f"""
                font-size: {tokens.font_size_large}px;
                color: {tokens.accent if self._favorite else tokens.text_disabled};
            """)

    @staticmethod
    def apply_style(widget: QWidget) -> None:
        """Apply card styling."""
        WidgetStyle.apply_card_style(widget)
        WidgetStyle.apply_card_shadow(widget)


# ---------------------------------------------------------------------------
# Connection panel
# ---------------------------------------------------------------------------

class ConnectionPanel(QFrame):
    """A modern connection control panel with connect/disconnect buttons."""

    def __init__(
        self,
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init(parent)
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._connected = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.spacing_l, tokens.spacing_m, tokens.spacing_l, tokens.spacing_m)
        layout.setSpacing(tokens.spacing_m)

        # Mode selector
        self._mode_label = QLabel("حالت اتصال: TUN")
        self._mode_label.setStyleSheet(f"""
            font-size: {tokens.font_size_body}px;
            color: {tokens.text_secondary};
        """)

        # Connect button
        self._connect_btn = AccentButton("اتصال")
        self._connect_btn.clicked.connect(self._on_connect or (lambda: None))

        # Disconnect button
        self._disconnect_btn = FlatButton("قطع", variant="danger")
        self._disconnect_btn.clicked.connect(self._on_disconnect or (lambda: None))

        # Settings button
        self._settings_btn = FlatButton("", variant="ghost")
        self._settings_btn.setFixedSize(40, 40)

        layout.addWidget(self._mode_label)
        layout.addStretch()
        layout.addWidget(self._connect_btn)
        layout.addWidget(self._disconnect_btn)
        layout.addWidget(self._settings_btn)

    def set_connected(self, connected: bool) -> None:
        """Update the connection state."""
        self._connected = connected
        self._connect_btn.setDisabled(connected)
        self._disconnect_btn.setDisabled(not connected)

        if connected:
            self._connect_btn.setText("متصل شده")
            self._connect_btn.set_variant("success")
        else:
            self._connect_btn.setText("اتصال")
            self._connect_btn.set_variant("primary")

    def set_mode(self, mode: str) -> None:
        """Update the connection mode label."""
        self._mode_label.setText(f"حالت اتصال: {mode}")


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

class SidebarNav(QFrame):
    """A modern sidebar navigation with icon buttons."""

    def __init__(
        self,
        on_item_selected: Callable[[str], None] | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init(parent)
        self._on_item_selected = on_item_selected
        self._items: list[tuple[str, str]] = [
            ("dashboard", "داشبورد"),
            ("servers", "سرورها"),
            ("scanner", "اسکنر"),
            ("settings", "تنظیمات"),
        ]
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.spacing_m, tokens.spacing_xl, tokens.spacing_m, tokens.spacing_m)
        layout.setSpacing(tokens.spacing_m)

        # Logo
        self._logo = QLabel("dicodePing")
        self._logo.setStyleSheet(f"""
            font-size: {tokens.font_size_xlarge}px;
            font-weight: 700;
            color: {tokens.text_primary};
            padding: {tokens.spacing_m}px 0;
        """)
        layout.addWidget(self._logo)

        layout.addSpacing(tokens.spacing_l)

        # Nav items
        self._buttons: dict[str, QPushButton] = {}
        for item_id, label in self._items:
            btn = FlatButton(label, variant="ghost")
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda _, iid=item_id: self._on_item_selected(iid) if self._on_item_selected else None)
            layout.addWidget(btn)
            self._buttons[item_id] = btn

        layout.addStretch()

        # Version label
        version_label = QLabel("v3.0.0 (پیش‌انتشار)")
        version_label.setStyleSheet(f"""
            font-size: {tokens.font_size_small}px;
            color: {tokens.text_disabled};
            padding: {tokens.spacing_m}px 0;
        """)
        layout.addWidget(version_label)


# ---------------------------------------------------------------------------
# Dashboard view
# ---------------------------------------------------------------------------

class DashboardView(QWidget):
    """A dashboard view showing connection summary and quick stats."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.spacing_l, tokens.spacing_l, tokens.spacing_l, tokens.spacing_l)
        layout.setSpacing(tokens.spacing_l)

        # Quick connect section
        quick_card = Card()
        quick_layout = QVBoxLayout(quick_card)
        quick_layout.setContentsMargins(tokens.spacing_l, tokens.spacing_l, tokens.spacing_l, tokens.spacing_l)

        title = QLabel("اتصال سریع")
        title.setStyleSheet(f"""
            font-size: {tokens.font_size_large}px;
            font-weight: 700;
            color: {tokens.text_primary};
        """)

        self._connect_btn = AccentButton("اتصال خودکار (بهترین سرور)")
        self._connect_btn.setFixedHeight(48)

        quick_layout.addWidget(title)
        quick_layout.addSpacing(tokens.spacing_m)
        quick_layout.addWidget(self._connect_btn)

        layout.addWidget(quick_card)

        # Stats row
        stats_card = Card()
        stats_layout = QHBoxLayout(stats_card)
        stats_layout.setContentsMargins(tokens.spacing_l, tokens.spacing_m, tokens.spacing_l, tokens.spacing_m)

        self._ping_value = QLabel("—")
        self._traffic_value = QLabel("—")
        self._uptime_value = QLabel("—")

        for label_text, value_widget in [
            ("پینگ", self._ping_value),
            ("ترافیک", self._traffic_value),
            ("زمان اتصال", self._uptime_value),
        ]:
            column = QVBoxLayout()
            label = QLabel(label_text)
            label.setStyleSheet(f"color: {tokens.text_secondary}; font-size: {tokens.font_size_small}px;")
            value_widget.setStyleSheet(f"color: {tokens.text_primary}; font-weight: 600;")
            column.addWidget(label)
            column.addWidget(value_widget)
            stats_layout.addLayout(column)
            if label_text != "زمان اتصال":
                stats_layout.addSpacing(tokens.spacing_l)

        layout.addWidget(stats_card)


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class MainWindowV3(QMainWindow):
    """Modern main application window for dicodePing Version 3."""

    def __init__(self) -> None:
        super().__init__()
        self._setup_window()
        self._setup_ui()
        self._apply_theme()

    def _setup_window(self) -> None:
        self.setWindowTitle("dicodePing v3.0.0")
        self.resize(1200, 720)
        self.setObjectName("MainWindow")

    def _setup_ui(self) -> None:
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header bar
        header = QFrame()
        header.setFixedHeight(tokens.header_height)
        header.setStyleSheet(f"""
            background: {tokens.surface};
            border-bottom: 1px solid {tokens.border};
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(tokens.spacing_l, 0, tokens.spacing_l, 0)

        title = QLabel("dicodePing v3.0.0 (پیش‌انتشار)")
        title.setStyleSheet(f"""
            font-size: {tokens.font_size_medium}px;
            font-weight: 600;
            color: {tokens.text_primary};
        """)
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Theme toggle button
        self._theme_btn = FlatButton("🌓", variant="ghost")
        self._theme_btn.setFixedSize(40, 32)
        self._theme_btn.clicked.connect(self._toggle_theme)
        header_layout.addWidget(self._theme_btn)

        main_layout.addWidget(header)

        # Main content area with sidebar + stacked widget
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(tokens.spacing_l, tokens.spacing_l, tokens.spacing_l, tokens.spacing_l)
        content_layout.setSpacing(tokens.spacing_l)

        # Sidebar
        self.sidebar = SidebarNav(on_item_selected=self._on_nav_item_selected)
        content_layout.addWidget(self.sidebar, 0, Qt.AlignTop)

        # Stacked widget for views
        self._stack = QStackedWidget()

        # Create views
        self.dashboard_view = DashboardView()
        self._stack.addWidget(self.dashboard_view)

        content_layout.addWidget(self._stack, 1)

        main_layout.addLayout(content_layout)

        # Status bar
        self.status_bar = StatusBar()
        main_layout.addWidget(self.status_bar)

    def _setup_connections(self) -> None:
        """Connect signals to slots for the v2rayN integration."""
        # Connect the connect button to the v2rayN connection manager
        if hasattr(self, "dashboard_view") and hasattr(self.dashboard_view, "_connect_btn"):
            self.dashboard_view._connect_btn.clicked.connect(self._on_connect_clicked)

    def _on_connect_clicked(self) -> None:
        """Handle connect button click."""
        self.status_bar.set_state("connecting")
        # The actual connection logic is handled by the v2rayN integration layer
        # This is connected by the main app when wiring up the connection manager

    def _on_nav_item_selected(self, item_id: str) -> None:
        """Handle sidebar navigation item selection."""
        # Switch the stacked widget to the corresponding view
        if item_id in self._stack_widgets:
            self._stack.setCurrentWidget(self._stack_widgets[item_id])

    def _toggle_theme(self) -> None:
        """Toggle between dark and light themes."""
        new_theme = theme_manager.toggle()
        self._apply_theme()
        self._theme_btn.setText("☀️" if new_theme == "dark" else "🌙")

    def _apply_theme(self) -> None:
        """Apply the current theme to the window."""
        theme_manager.apply_palette(QApplication.instance())

    def add_server_card(self, **kwargs) -> ServerCard:
        """Add a server card to the dashboard."""
        card = ServerCard(**kwargs)
        return card

    def update_status(self, state: str, ping_ms: int | None = None) -> None:
        """Update the status bar."""
        self.status_bar.set_state(state, ping_ms)

    def set_connected(self, connected: bool) -> None:
        """Update the connection state."""
        pass  # Handled by the connection panel


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "MainWindowV3",
    "DashboardView",
    "ServerCard",
    "ConnectionPanel",
    "StatusBar",
    "SidebarNav",
    "Card",
    "FlatButton",
    "AccentButton",
    "ThemeManager",
    "WidgetStyle",
    "tokens",
    "theme_manager",
]
