from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from dicodeping.desktop_proxy import DesktopProxyController
from dicodeping.xray import XrayManager, build_tun_config, ensure_xray

ROOT = Path(__file__).resolve().parents[1]

VLESS = (
    "vless://11111111-1111-1111-1111-111111111111@example.com:443"
    "?encryption=none&security=tls&sni=example.com&type=ws&host=example.com&path=%2Fws"
)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _tun(config: dict) -> dict:
    return next(item for item in config["inbounds"] if item.get("protocol") == "tun")


def test_desktop_xray_is_system_wide_tun_with_private_validation_socks() -> None:
    config = build_tun_config(
        VLESS,
        validation_socks_port=18080,
        api_port=18082,
        platform_name="Windows",
        outbound_bind_ip="192.168.1.20",
    )
    inbounds = {item["tag"]: item for item in config["inbounds"]}
    assert set(inbounds) == {"tun-in", "validation-socks"}
    assert inbounds["tun-in"]["port"] == 0
    assert inbounds["tun-in"]["settings"]["autoSystemRoutingTable"] == ["0.0.0.0/0", "::/0"]
    assert inbounds["tun-in"]["settings"]["autoOutboundsInterface"] == "auto"
    assert inbounds["validation-socks"]["listen"] == "127.0.0.1"
    assert config["outbounds"][0]["sendThrough"] == "192.168.1.20"


def test_tun_settings_are_valid_for_windows_linux_and_macos() -> None:
    windows = _tun(build_tun_config(VLESS, platform_name="Windows"))["settings"]
    linux = _tun(build_tun_config(VLESS, platform_name="Linux"))["settings"]
    macos = _tun(build_tun_config(VLESS, platform_name="Darwin", tun_name="utun233"))["settings"]
    assert windows["name"] == "dicodePing-TUN"
    assert windows["desc"] == "dicodePing"
    assert windows["dns"] == ["1.1.1.1", "8.8.8.8"]
    assert linux["name"] == "dicodePing-TUN"
    assert "dns" not in linux
    assert macos["name"] == "utun233"
    assert macos["name"].startswith("utun")


def test_windows_core_preparation_requires_wintun(tmp_path: Path) -> None:
    executable = tmp_path / "xray.exe"
    executable.write_bytes(b"x")
    with (
        patch("dicodeping.xray.find_xray", return_value=executable),
        patch("dicodeping.xray._core_version_matches", return_value=True),
        patch("dicodeping.xray.ensure_wintun", return_value=tmp_path / "wintun.dll") as ensure_wintun_mock,
    ):
        assert ensure_xray(language="en", require_wintun=True) == executable
    ensure_wintun_mock.assert_called_once()


def test_proxy_recovery_file_survives_failed_restore(tmp_path: Path) -> None:
    state_path = tmp_path / "proxy-state.json"
    state_path.write_text(json.dumps({"backend": "windows-registry"}), encoding="utf-8")
    controller = DesktopProxyController(state_path)
    with patch.object(controller, "_restore_state", side_effect=RuntimeError("desktop unavailable")):
        assert controller.restore() is False
    assert state_path.is_file()


def test_proxy_recovery_file_is_removed_after_successful_restore(tmp_path: Path) -> None:
    state_path = tmp_path / "proxy-state.json"
    state_path.write_text(json.dumps({"backend": "process-environment", "previous": {}}), encoding="utf-8")
    controller = DesktopProxyController(state_path)
    with patch.object(controller, "_restore_state", return_value=None):
        assert controller.restore() is True
    assert not state_path.exists()


def test_traffic_stats_counts_tun_inbound() -> None:
    class AliveProcess:
        @staticmethod
        def poll():
            return None

    manager = XrayManager()
    manager.process = AliveProcess()
    manager.executable = Path("xray")
    manager.api_port = 10085
    payload = {
        "stat": [
            {"name": "inbound>>>tun-in>>>traffic>>>uplink", "value": "300"},
            {"name": "inbound>>>tun-in>>>traffic>>>downlink", "value": "400"},
        ]
    }
    completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
    with patch("dicodeping.xray.subprocess.run", return_value=completed):
        assert manager.traffic_stats() == (300, 400)
    manager.process = None


def test_rc19_desktop_launchers_require_tun_privileges_and_wintun() -> None:
    app = read("app.py")
    windows_builder = read("tools/build_windows.py")
    prepare_core = read("tools/prepare_core.py")
    workers = read("dicodeping/workers.py")
    assert "relaunch_as_admin()" in app
    assert "Administrator/root access is required for Xray TUN mode" in app
    assert "--uac-admin" in windows_builder
    assert "wintun.dll" in windows_builder
    assert "require_wintun=is_windows()" in prepare_core
    assert "manager.connected_ping(timeout=3.2)" in workers


def test_rc19_runtime_uses_tun_not_system_proxy() -> None:
    xray = read("dicodeping/xray.py")
    start = xray[xray.index("    def start("):xray.index("    def traffic_stats(")]
    assert "config = build_tun_config(" in start
    assert "_direct_tun_http_probe" in start
    assert "autoOutboundsInterface" in xray
    assert "install_direct_host_routes" in start
    assert "self._system_proxy.enable" not in start
    assert 'self.route_mode = f"tun:{active_tun_name}"' in start


def test_modern_grpc_share_fields_are_preserved() -> None:
    from dicodeping.protocols import build_xray_outbound

    raw = (
        "vless://11111111-1111-1111-1111-111111111111@1.2.3.4:443"
        "?encryption=none&security=tls&type=grpc&host=grpc.example.com"
        "&serviceName=my-service&mode=multi&packetEncoding=xudp"
    )
    outbound = build_xray_outbound(raw)
    assert outbound is not None
    stream = outbound["streamSettings"]
    assert stream["tlsSettings"]["serverName"] == "grpc.example.com"
    assert stream["grpcSettings"]["authority"] == "grpc.example.com"
    assert stream["grpcSettings"]["serviceName"] == "my-service"
    assert stream["grpcSettings"]["multiMode"] is True
    assert outbound["settings"]["vnext"][0]["users"][0]["packetEncoding"] == "xudp"
