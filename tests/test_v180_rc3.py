from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from dicodeping import core_manager
from dicodeping.connection_manager import AlternativeCoreManager
from dicodeping.config_profile import classify_config_profile
from dicodeping.core_runtime import (
    CoreState,
    LifecycleController,
    PORT_REGISTRY,
    PROCESS_REGISTRY,
)
from dicodeping.crawler import extract_configs, load_channel_specs
from dicodeping.scanner import normalize_rank_limit


ROOT = Path(__file__).resolve().parents[1]


def test_rc3_versions_are_consistent():
    assert 'RELEASE_VERSION = "1.9.0-rc.13"' in (ROOT / "dicodeping/constants.py").read_text("utf-8")
    assert '__version__ = "1.9.0rc13"' in (ROOT / "dicodeping/__init__.py").read_text("utf-8")
    gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text("utf-8")
    assert 'versionName = "1.9.0-rc.13"' in gradle
    assert "versionCode = 48" in gradle


def test_manifest_is_sha_only_fallback_and_never_claims_signature():
    manifest = json.loads((ROOT / "assets/core-manifest.json").read_text("utf-8"))
    assert manifest["integrity"] == "SHA-256 verified"
    assert isinstance(manifest["signature"], dict)
    assert "debug/test" in manifest["signature"]["windows"]
    assert "debug/test" in manifest["signature"]["macos"]
    assert "APK" in manifest["signature"]["android"]
    assert manifest["cores"]["psiphon"]["state"] == "missingAuthorizedConfig"


def test_manifest_pins_desktop_aether_and_warp_hashes():
    manifest = json.loads((ROOT / "assets/core-manifest.json").read_text("utf-8"))
    for core_id in ("aether", "warp"):
        for platform in ("windows-x64", "linux-x86_64"):
            assert manifest["cores"][core_id][platform]["url"].startswith("https://github.com/")
            assert len(manifest["cores"][core_id][platform]["sha256"]) == 64


def test_rank_limits_default_on_invalid_values():
    assert normalize_rank_limit(1) == 1
    assert normalize_rank_limit(20) == 20
    assert normalize_rank_limit(0) == 8
    assert normalize_rank_limit(21) == 8
    assert normalize_rank_limit("bad") == 8


def test_canonical_channel_assets_are_identical():
    desktop = json.loads((ROOT / "assets/channels.json").read_text("utf-8"))
    android = json.loads(
        (ROOT / "dicodePing_android/app/src/main/assets/channels.json").read_text("utf-8")
    )
    assert desktop == android
    assert {row["rank"] for row in desktop["channels"]} == {1, 2}
    assert load_channel_specs()


def test_telegram_proxy_links_are_rejected():
    page = (
        "tg://proxy?server=1.2.3.4 t.me/proxy?server=1.2.3.4 "
        "tg://socks?server=1.2.3.4 vless://id@example.com:443?security=tls"
    )
    found = extract_configs(page)
    assert len(found) == 1
    assert found[0].startswith("vless://")


def test_scanner_has_no_continue_on_bootstrap_or_disconnect():
    scanner = (ROOT / "dicodeping/scanner.py").read_text("utf-8")
    assert "continuing anyway" not in scanner
    assert "continuing with probe anyway" not in scanner
    assert "contaminationRisk" in scanner
    assert "save_scanner_transaction" in scanner


def test_scanner_uses_bounded_probe_queue_and_real_http_probe():
    scanner = (ROOT / "dicodeping/scanner.py").read_text("utf-8")
    checker = (ROOT / "dicodeping/config_checker.py").read_text("utf-8")
    xray = (ROOT / "dicodeping/xray.py").read_text("utf-8")
    assert "SCAN_PROBE_WORKERS = min(10" in scanner
    assert "while len(future_to_raw) < SCAN_PROBE_QUEUE_LIMIT" in scanner
    assert "probe_outbound_delay" in checker
    assert "_socks_http_probe" in xray
    assert "/generate_204" in xray


def test_archive_rejects_zip_slip(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.exe", b"x")
    with pytest.raises(RuntimeError, match="unsafe archive member"):
        core_manager._extract_archive(archive, tmp_path / "out", "zip")


def test_archive_rejects_suspicious_compression_ratio(tmp_path: Path):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("payload.bin", b"0" * (2 * 1024 * 1024))
    with pytest.raises(RuntimeError, match="compression ratio"):
        core_manager._extract_archive(archive, tmp_path / "out", "zip")


def test_archive_rejects_too_many_members(tmp_path: Path):
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for index in range(core_manager.MAX_ARCHIVE_MEMBERS + 1):
            bundle.writestr(f"{index}.txt", b"x")
    with pytest.raises(RuntimeError, match="too many members"):
        core_manager._extract_archive(archive, tmp_path / "out", "zip")


def test_download_rejects_unapproved_host_before_network(tmp_path: Path):
    with pytest.raises(RuntimeError, match="approved HTTPS host"):
        core_manager._download_file("https://example.invalid/core.zip", tmp_path / "core.zip")


def test_lifecycle_generation_cancels_previous_operation():
    lifecycle = LifecycleController()
    first = lifecycle.begin(CoreState.STARTING)
    second = lifecycle.begin(CoreState.STARTING)
    assert first.is_cancelled()
    assert second.generation == first.generation + 1
    assert not lifecycle.transition(first, CoreState.CONNECTED)
    assert lifecycle.transition(second, CoreState.CONNECTED)


def test_port_registry_returns_unique_ports():
    first = PORT_REGISTRY.acquire()
    second = PORT_REGISTRY.acquire()
    try:
        assert first != second
    finally:
        PORT_REGISTRY.release(first)
        PORT_REGISTRY.release(second)


def test_process_registry_stops_owned_child():
    process = PROCESS_REGISTRY.register(
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            start_new_session=sys.platform != "win32",
        )
    )
    PROCESS_REGISTRY.stop(process, timeout=0.2)
    assert process.poll() is not None


def test_alternative_stats_are_explicitly_unsupported():
    manager = AlternativeCoreManager("aether")
    try:
        assert manager.traffic_stats() == (None, None)
    finally:
        manager.stop()


def test_android_has_no_external_app_or_raw_binary_path():
    manager = (
        ROOT
        / "dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidCoreManager.kt"
    ).read_text("utf-8")
    manifest = (ROOT / "dicodePing_android/app/src/main/AndroidManifest.xml").read_text("utf-8")
    assert "ShirOKhorshid" not in manager
    assert "com.termux" not in manager + manifest
    assert "REQUEST_INSTALL_PACKAGES" not in manifest
    assert "unsupportedInThisBuild" in manager


def test_android_scanner_is_service_owned_and_no_auto_reconnect():
    fragment = (
        ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt"
    ).read_text("utf-8")
    coordinator = (
        ROOT
        / "dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt"
    ).read_text("utf-8")
    assert "ScannerService" in fragment
    assert "viewLifecycleOwner.lifecycleScope.launch" in fragment  # rendering only
    assert "vm.repo.bestServer()?.let" not in fragment + coordinator
    assert "contaminationRisk" in coordinator


def test_android_scanner_has_no_volume_feature():
    fragment = (
        ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt"
    ).read_text("utf-8")
    layout = (ROOT / "dicodePing_android/app/src/main/res/layout/fragment_scanner.xml").read_text("utf-8")
    assert "VolumeDetector" not in fragment
    assert "volumeFetchButton" not in fragment + layout
    assert "SubscriptionClient" not in fragment


def test_android_scanner_routes_crawl_through_bootstrap_and_saves_transactionally():
    coordinator = (
        ROOT
        / "dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt"
    ).read_text("utf-8")
    repository = (
        ROOT
        / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt"
    ).read_text("utf-8")
    crawler = (
        ROOT
        / "dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt"
    ).read_text("utf-8")
    assert "requireConnectedBootstrap()" in coordinator
    assert "Dashboard Xray VPN is connected and HTTP-verified" in coordinator
    assert "connectBootstrap()" not in coordinator
    assert "onSaving" in coordinator
    assert "saveScannerTransaction" in repository
    assert '"rawSubscription"' in repository
    assert '"base64Subscription"' in repository
    assert "ssr|snell" not in crawler
    assert "hysteria2|hy2|tuic" not in crawler
    assert "retryOnConnectionFailure(true)" in crawler


def test_android_xray_is_updated_and_hash_pinned():
    gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text("utf-8")
    assert 'coreVersion = "26.7.11"' in gradle
    assert "0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352" in gradle


def test_scanner_keeps_five_verified_servers_and_profiles_are_conservative():
    scanner = (ROOT / "dicodeping/scanner.py").read_text("utf-8")
    android_repo = (
        ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt"
    ).read_text("utf-8")
    assert "SCAN_MAX_SERVERS = 80" in scanner
    assert "SCANNER_HEALTHY_TARGET = 60" in android_repo
    assert classify_config_profile("vless://id@demo.workers.dev:443") == "worker"
    assert classify_config_profile("vless://id@example.test:443#10GB") == "limited"
    assert classify_config_profile("vless://id@example.test:443#permanent") == "persistent"
    assert classify_config_profile("vless://id@example.test:443") == "unknown"
