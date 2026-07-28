from pathlib import Path

from dicodeping import connection_manager as module
from dicodeping.connection_manager import AlternativeCoreManager
from dicodeping.volume import humanize_limit_label


def test_warp_http2_flag_belongs_to_socks_subcommand(tmp_path, monkeypatch):
    warp = tmp_path / "warp"
    warp.mkdir()
    (warp / "config.json").write_text(
        '{"private_key":"k","endpoint_pub_key":"p","ipv4":"172.16.0.2"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "core_dir", lambda _core: warp)
    manager = AlternativeCoreManager("warp")
    manager.socks_port = 1820
    command = manager._command(tmp_path / "usque", tmp_path, {}, transport="http2")
    assert command[:4] == [str(tmp_path / "usque"), "-c", str(warp / "config.json"), "socks"]
    assert command.index("--http2") > command.index("socks")
    assert "--always-reconnect" in command


def test_aether_has_explicit_config_and_bind(tmp_path, monkeypatch):
    aether = tmp_path / "aether"
    aether.mkdir()
    monkeypatch.setattr(module, "core_dir", lambda _core: aether)
    manager = AlternativeCoreManager("aether")
    manager.socks_port = 1819
    manager._options = {"protocol": "masque", "scan": "balanced", "quick_reconnect": True}
    env = {}
    command = manager._command(tmp_path / "aether-bin", tmp_path, env, transport="http2")
    assert command[1:3] == ["--config", str(aether / "aether.toml")]
    assert ["--bind", "127.0.0.1:1819"] == command[command.index("--bind"):command.index("--bind") + 2]
    assert "--h2" in command
    assert env["AETHER_MASQUE_HTTP2"] == "1"


def test_compact_validity_labels_are_expanded():
    assert humanize_limit_label("8d", "fa") == "اعتبار 8 روز"
    assert humanize_limit_label("2w", "en") == "2 weeks validity"
