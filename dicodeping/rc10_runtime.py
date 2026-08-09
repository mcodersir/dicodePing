"""RC4 presentation fixes applied after the legacy compatibility layers."""
from __future__ import annotations

from .conn_methods import METHOD_AETHER, METHOD_WARP

_PATCHED = False


def _core_name(core_id: str) -> str:
    if core_id == METHOD_AETHER:
        return "Aether (Ironclad)"
    if core_id == METHOD_WARP:
        return "WARP / Usque"
    return core_id.title()


def install_rc10_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    from .ui import MainWindow, repolish, tinted_icon

    original_init = MainWindow.__init__
    original_render = MainWindow.render_servers
    original_summary = MainWindow._render_home_summary
    original_update = MainWindow.update_connection_ui

    def apply_alternative_home(self) -> bool:
        core_id = getattr(self.manager, "active_core", "xray")
        if core_id == "xray":
            return False
        core_name = _core_name(core_id)
        connected = self.manager.connected
        busy = bool(self.worker)

        for index in (1, 2):
            self.sidebar.buttons[index].setEnabled(False)
        self.home_scan_button.setVisible(False)
        self.home_refresh_button.setVisible(False)
        self.home_open_servers_button.setVisible(False)
        self.home_target_widget.setVisible(False)
        self.hero_divider.setVisible(False)
        self.hero_divider.setMaximumWidth(0)
        for card in self.home_stat_cards:
            card.setVisible(False)
        self.home_recent_card.setVisible(False)
        self.home_best_flag.setVisible(False)
        self.home_target_label.setText(self.t("active_connection_core"))
        self.home_best_name.setText(core_name)
        self.home_best_meta.setText(self.t("alternative_core_integrity"))
        self.home_page_subtitle_label.setText(
            self.t("alternative_home_subtitle", core=core_name)
        )

        if connected:
            self.live_metrics_card.setVisible(True)
            self._set_status_visual("online", self.t("connected"))
            self.home_hero_title.setText(self.t("connected"))
            self.home_hero_detail.setText(
                self.t("alternative_core_connected", core=core_name)
            )
            self.home_primary_button.setText(self.t("disconnect"))
            self.home_primary_button.setIcon(tinted_icon("power.svg"))
            self.home_primary_button.setProperty("kind", "danger")
        elif busy:
            self.live_metrics_card.setVisible(False)
            self._set_status_visual("busy", self.t("processing"))
            self.home_hero_title.setText(self.t("connecting_button"))
            self.home_hero_detail.setText(
                self.t("alternative_core_ready", core=core_name)
            )
            self.home_primary_button.setText(self.t("cancel_connection"))
            self.home_primary_button.setIcon(tinted_icon("refresh.svg"))
            self.home_primary_button.setProperty("kind", "primary")
        else:
            self.live_metrics_card.setVisible(False)
            self._set_status_visual("offline", self.t("disconnected"))
            self.home_hero_title.setText(core_name)
            self.home_hero_detail.setText(
                self.t("alternative_core_ready", core=core_name)
            )
            self.home_primary_button.setText(
                self.t("alternative_core_connect", core=core_name)
            )
            self.home_primary_button.setIcon(tinted_icon("power.svg"))
            self.home_primary_button.setProperty("kind", "primary")
        self.sidebar.set_connection_state(connected, busy)
        repolish(self.home_primary_button)
        return True

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._rc4_apply_alternative_home()

    def render(self):
        original_render(self)
        self._rc4_apply_alternative_home()

    def summary(self):
        if not self._rc4_apply_alternative_home():
            original_summary(self)

    def update(self):
        original_update(self)
        self._rc4_apply_alternative_home()

    MainWindow.__init__ = init
    MainWindow.render_servers = render
    MainWindow._render_home_summary = summary
    MainWindow.update_connection_ui = update
    MainWindow._rc4_apply_alternative_home = apply_alternative_home
