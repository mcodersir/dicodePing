from __future__ import annotations

import json
from pathlib import Path

from dicodeping.xray import build_tun_config
from dicodeping.connection_manager import AlternativeCoreManager

ROOT = Path(__file__).resolve().parents[1]


def test_v190_versions_and_four_platform_release():
    assert 'RELEASE_VERSION = "1.9.0-rc.1"' in (ROOT / "dicodeping/constants.py").read_text("utf-8")
    assert '__version__ = "1.9.0rc1"' in (ROOT / "dicodeping/__init__.py").read_text("utf-8")
    workflow = (ROOT / ".github/workflows/v1.9.0-rc.1-release.yml").read_text("utf-8")
    for platform in ("windows", "linux", "macos", "android"):
        assert platform in workflow
    assert "prerelease: true" in workflow


def test_secure_dns_is_real_xray_doh():
    raw = "vless://11111111-1111-4111-8111-111111111111@example.com:443?security=tls&type=tcp#test"
    config = build_tun_config(raw, secure_dns=True)
    addresses = [item["address"] for item in config["dns"]["servers"]]
    assert addresses == [
        "https://cloudflare-dns.com/dns-query",
        "https://dns.google/dns-query",
    ]
    plain = build_tun_config(raw, secure_dns=False)
    assert plain["dns"]["servers"][0]["address"] == "1.1.1.1"


def test_optional_desktop_cores_are_bundled_by_build_pipeline():
    for name in ("build_windows.py", "build_linux.py", "build_macos.py"):
        text = (ROOT / "tools" / name).read_text("utf-8")
        assert "prepare_optional_cores" in text
        assert "aether" in text
        assert "usque" in text


def test_aether_profile_uses_real_cli_contract(tmp_path):
    manager = AlternativeCoreManager("aether")
    manager.socks_port = 1819
    manager._options = {
        "protocol": "wireguard",
        "scan": "balanced",
        "performance": "low",
        "quick_reconnect": False,
    }
    command = manager._command(tmp_path / "aether", tmp_path, {}, transport="http2")
    assert "--wireguard" in command
    assert command[command.index("--scan") + 1] == "balanced"
    assert command[command.index("--perf") + 1] == "low"
    assert "--no-quick-reconnect" in command
    assert "--h2" in command


def test_manifest_pins_macos_core_assets():
    manifest = json.loads((ROOT / "assets/core-manifest.json").read_text("utf-8"))
    for core_id in ("aether", "warp"):
        for platform in ("macos-arm64", "macos-x86_64"):
            item = manifest["cores"][core_id][platform]
            assert item["bundled"] is True
            assert len(item["sha256"]) == 64


def test_android_does_not_fake_termux_core_support():
    manager = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidCoreManager.kt").read_text("utf-8")
    assert "unsupportedInThisBuild" in manager
    assert "Runtime.getRuntime" not in manager
    service = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text("utf-8")
    assert "settings.secureDnsDoh" in service


def test_legal_notices_cover_every_reference():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    for project in ("Aether-GUI", "oblivion", "v2rayN", "Intra", "DicodeConfigChecker"):
        assert project in notices
