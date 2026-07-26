from __future__ import annotations

import inspect
import json
import subprocess
import threading
import types
from pathlib import Path

import dicodeping.connection_manager as connection_module
from dicodeping.connection_manager import AlternativeCoreManager, ConnectionManager, register_warp
from dicodeping.xray import XrayManager


def test_xray_start_accepts_shared_progress_contract() -> None:
    parameters = inspect.signature(XrayManager.start).parameters
    assert "progress_value" in parameters
    assert "core_options" in parameters


def test_facade_does_not_forward_alternative_options_to_xray(monkeypatch) -> None:
    xray = XrayManager()
    captured: dict[str, object] = {}

    def fake_start(self, raw_config: str = "", **kwargs) -> None:
        captured.update(kwargs)

    xray.start = types.MethodType(fake_start, xray)
    manager = ConnectionManager.__new__(ConnectionManager)
    manager._lock = threading.RLock()
    manager._manager = xray
    monkeypatch.setattr(connection_module, "get_active_core", lambda: "xray")

    manager.start("sample", core_options={"scan": "balanced"}, progress_value=lambda *_: None)

    assert "core_options" not in captured
    assert "progress_value" in captured



def test_aether_uses_persistent_config_directory(tmp_path, monkeypatch) -> None:
    manager = AlternativeCoreManager("aether")
    manager.socks_port = 18192
    manager._options = {"protocol": "masque", "scan": "balanced", "quick_reconnect": True}
    persistent = tmp_path / "user-data" / "aether"
    persistent.mkdir(parents=True)
    monkeypatch.setattr(connection_module, "core_dir", lambda _core_id: persistent)

    environment: dict[str, str] = {}
    command = manager._command(tmp_path / "bundle" / "aether.exe", tmp_path, environment)

    expected = str(persistent / "aether.toml")
    assert command[command.index("--config") + 1] == expected
    assert environment["AETHER_CONFIG"] == expected
    assert "--quick-reconnect" in command

def test_warp_command_places_root_flags_before_subcommand(tmp_path, monkeypatch) -> None:
    manager = AlternativeCoreManager("warp")
    manager.socks_port = 18191
    warp_dir = tmp_path / "warp"
    warp_dir.mkdir()
    (warp_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(connection_module, "core_dir", lambda _core_id: warp_dir)

    command = manager._command(tmp_path / "usque.exe", tmp_path, {}, transport="http2")

    assert command.index("--config") < command.index("socks")
    assert command.index("--http2") < command.index("socks")
    assert command[command.index("-b") + 1] == "127.0.0.1"
    assert command[command.index("-p") + 1] == "18191"


def test_warp_registration_is_atomic_and_noninteractive(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "usque.exe"
    executable.write_bytes(b"stub")
    warp_dir = tmp_path / "data" / "warp"
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        config_path = Path(command[command.index("--config") + 1])
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"private_key": "secret", "endpoint_pub_key": "public"}),
            encoding="utf-8",
        )
        assert kwargs["stdin"] is subprocess.DEVNULL
        return subprocess.CompletedProcess(command, 0, "Successful registration", "")

    monkeypatch.setattr(connection_module, "resolve_core_path", lambda _core_id: executable)
    monkeypatch.setattr(connection_module, "core_dir", lambda _core_id: warp_dir)
    monkeypatch.setattr(connection_module.subprocess, "run", fake_run)

    result = register_warp(accept_terms=True)

    assert result == warp_dir / "config.json"
    assert result.is_file()
    assert not (warp_dir / "config.registering.json").exists()
    assert "register" in calls[0]
    assert "--accept-tos" in calls[0]


def test_rc2_has_background_activation_and_visible_progress() -> None:
    source = Path("dicodeping/ui.py").read_text(encoding="utf-8")
    assert "CoreActivationThread" in source
    assert "self.conn_method_progress.setVisible(True)" in source
    assert "worker.progress.connect(self.update_progress)" in source
