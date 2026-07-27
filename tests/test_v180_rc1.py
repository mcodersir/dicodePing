from pathlib import Path

from dicodeping.conn_methods import apply_cdn_formatting
from dicodeping.scanner import generate_sub_name


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_and_optional_cores_are_not_bundled():
    constants = (ROOT / "dicodeping/constants.py").read_text(encoding="utf-8")
    spec = (ROOT / "dicodePing.spec").read_text(encoding="utf-8")
    assert 'RELEASE_VERSION = "1.8.0-rc.2"' in constants
    assert "aether" not in spec.lower()
    assert "psiphon-tunnel-core" not in spec.lower()


def test_scanner_preserves_and_sanitizes_user_source_name():
    assert generate_sub_name("  Office scan  ") == "SUB"
    assert generate_sub_name('bad<>:"/\\|?*name') == "SUB"
    assert generate_sub_name("") == "SUB"


def test_cdn_formatting_keeps_origin_as_vless_host_and_sni():
    raw = "vless://abc@example.com:443?security=tls&type=ws#server"
    formatted = apply_cdn_formatting(raw, "speed.cloudflare.com")
    assert "@speed.cloudflare.com:443" in formatted
    assert "sni=example.com" in formatted
    assert "host=example.com" in formatted


def test_android_per_app_is_wired_from_settings_to_vpn_builder():
    settings = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/SettingsFragment.kt").read_text(encoding="utf-8")
    service = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt").read_text(encoding="utf-8")
    assert "store.perAppVpnMode" in settings
    assert "store.perAppVpnPackages" in settings
    assert "builder.addAllowedApplication" in service
    assert "builder.addDisallowedApplication" in service


def test_platform_sharing_has_real_backends_and_cleanup():
    desktop = (ROOT / "dicodeping/vpn_sharing.py").read_text()
    android_rooted = (
        ROOT
        / "dicodePing_android/app/src/rooted/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
    ).read_text()
    android_standard = (
        ROOT
        / "dicodePing_android/app/src/standard/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
    ).read_text()
    assert "HNetCfg.HNetShare" in desktop
    assert "hostapd" in desktop and "dnsmasq" in desktop
    assert "DICODEPING_SHARE" in android_rooted
    assert "ip rule del" in android_rooted
    assert "ProcessBuilder" not in android_standard


def test_optional_core_downloads_are_sha_verified_and_atomic():
    desktop = (ROOT / "dicodeping/core_manager.py").read_text()
    android = (
        ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidCoreManager.kt"
    ).read_text()
    assert "integrity check failed" in desktop
    assert "unsafe archive member" in desktop
    assert "AndroidExternalCoreProcess" in android
    assert "initializeWarp" in android
    prepare = (ROOT / "dicodePing_android/tools/prepare_bundled_cores.py").read_text()
    assert "verify_upstream_sha" in prepare
    assert 'USQUE_VERSION = "4.2.1"' in prepare
