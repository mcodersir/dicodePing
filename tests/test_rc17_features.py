from pathlib import Path

from dicodeping.models import ServerRecord
from dicodeping.resource_tuning import build_resource_profile, resource_mode_from_settings
from dicodeping.security_rating import assess_config_security

ROOT = Path(__file__).resolve().parents[1]


def test_security_rating_is_conservative_and_persisted():
    strong = assess_config_security("vless://id@example.com:443?security=reality&type=grpc&sni=example.com")
    weak = assess_config_security("socks://example.com:1080")
    assert strong.score > weak.score
    assert strong.level == "high"
    row = ServerRecord("id", "name", "VLESS", "example.com", 443, "blob", security_score=strong.score, security_level=strong.level, security_summary=strong.summary)
    restored = ServerRecord.from_dict(row.to_dict())
    assert restored.security_score == strong.score


def test_resource_mode_defaults_optimized_and_professional_is_bounded():
    assert resource_mode_from_settings({}) == "optimized"
    optimized = build_resource_profile(cpu_count=8, memory_bytes=8 * 1024**3, mode="optimized")
    professional = build_resource_profile(cpu_count=8, memory_bytes=8 * 1024**3, mode="professional")
    assert professional.probe_workers >= optimized.probe_workers
    assert professional.network_buffer_kib >= optimized.network_buffer_kib
    assert professional.probe_workers <= 64


def test_scanner_enriches_geo_before_atomic_save():
    scanner = (ROOT / "dicodeping/scanner.py").read_text("utf-8")
    assert "_enrich_scanner_records(records, store=store, log=_log)" in scanner
    assert scanner.index("_enrich_scanner_records(records") < scanner.index("save_scanner_transaction(")


def test_android_rc17_security_location_resource_and_aether_pipeline():
    models = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/Models.kt").read_text("utf-8")
    repo = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt").read_text("utf-8")
    prepare = (ROOT / "dicodePing_android/tools/prepare_bundled_cores.py").read_text("utf-8")
    assert "securityScore" in models and "securityLevel" in models
    assert "locateServerSnapshot(healthy)" in repo
    assert "QW-AI-Code/Aether.git" in prepare
    assert "AETHER_MOBILE_COMMIT" in prepare
    assert '("arm64-v8a", "aarch64-linux-android")' in prepare
    assert '("x86_64", "x86_64-linux-android")' in prepare


def test_rc17_versions_and_deployer():
    constants = (ROOT / "dicodeping/constants.py").read_text("utf-8")
    gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text("utf-8")
    workflow = (ROOT / ".github/workflows/release.yml").read_text("utf-8")
    deploy = (ROOT / "DEPLOY_PRERELEASE_RC17.bat").read_text("utf-8")
    assert 'RELEASE_VERSION = "1.9.0-rc.17"' in constants
    assert 'versionName = "1.9.0-rc.17"' in gradle
    assert 'versionCode = 52' in gradle
    assert 'v1.9.0-rc.17' in workflow
    assert 'v1.9.0-rc.17' in deploy


def test_remote_discovery_assigns_security_rating():
    service = (ROOT / "dicodeping/service.py").read_text("utf-8")
    assert "security = assess_config_security(endpoint.raw, endpoint.host)" in service
    assert "security_score=security.score" in service


def test_release_installs_rust_android_core_toolchain():
    workflow = (ROOT / ".github/workflows/release.yml").read_text("utf-8")
    assert "dtolnay/rust-toolchain@stable" in workflow
    assert "cargo install cargo-ndk --locked" in workflow


def test_scanner_uses_fast_persistent_geo_path():
    scanner = (ROOT / "dicodeping/scanner.py").read_text("utf-8")
    geo = (ROOT / "dicodeping/geo.py").read_text("utf-8")
    android = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt").read_text("utf-8")
    assert "resolve_many(ips, fast=True)" in scanner
    assert "lookup_geo_fast if fast else lookup_geo" in geo
    assert "geo.resolveFast(ip)" in android
    assert 'ProgressState(true, "geo"' in android
