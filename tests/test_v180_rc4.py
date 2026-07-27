from pathlib import Path

from dicodeping.connection_manager import AlternativeCoreManager
from dicodeping.models import ServerRecord
from dicodeping.xray import build_tun_config


ROOT = Path(__file__).resolve().parents[1]
RAW = (
    "vless://11111111-1111-1111-1111-111111111111@example.com:443"
    "?security=tls&type=tcp#rc4"
)


def test_latency_fields_round_trip_without_conflation() -> None:
    row = ServerRecord(
        id="one",
        name="One",
        protocol="VLESS",
        host="example.com",
        port=443,
        config_blob="blob",
        icmp_ms=184,
        ping_ms=811,
        status="online",
    )
    restored = ServerRecord.from_dict(row.to_dict())
    assert restored.icmp_ms == 184
    assert restored.ping_ms == 811


def test_tun_profile_has_private_http_validation_inbound_and_api_route() -> None:
    config = build_tun_config(
        RAW,
        api_port=19191,
        validation_socks_port=19192,
    )
    tags = {str(item.get("tag")) for item in config["inbounds"]}
    assert {"tun-in", "validation-socks"} <= tags
    assert any(
        rule.get("inboundTag") == ["api"] and rule.get("outboundTag") == "api"
        for rule in config["routing"]["rules"]
    )


def test_alternative_cores_have_filtered_network_fallback() -> None:
    aether = AlternativeCoreManager("aether")
    aether.socks_port = 18081
    aether_h2 = aether._command(Path("aether"), Path("."), {}, transport="http2")
    assert aether_h2[aether_h2.index("--scan") + 1] == "balanced"
    assert "--h2" in aether_h2
    assert "--noize" in aether_h2

    warp = AlternativeCoreManager("warp")
    warp.socks_port = 18082
    source = (ROOT / "dicodeping/connection_manager.py").read_text(encoding="utf-8")
    assert 'transport == "http2"' in source
    assert 'command.append("--http2")' in source


def test_desktop_live_language_and_core_specific_home_are_wired() -> None:
    ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
    assert "def _apply_language_live" in ui
    assert "application.setLayoutDirection(direction)" in ui
    assert "self.body_layout.addWidget(self.sidebar, 0)" in ui
    assert "alternative_core_connect" in ui
    assert "self.home_recent_card.setVisible(not alternative)" in ui
    assert "install_rc10_patches," in (ROOT / "app_v190_rc4.py").read_text(encoding="utf-8")


def test_table_names_both_latency_semantics() -> None:
    ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
    i18n = (ROOT / "dicodeping/i18n.py").read_text(encoding="utf-8")
    assert 'self.t("latency_columns")' in ui
    assert '"latency_columns": "ICMP / Xray HTTP"' in i18n
    assert "row.icmp_ms = latency" in (ROOT / "dicodeping/rc7_runtime.py").read_text(
        encoding="utf-8"
    )
