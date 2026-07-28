from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from dicodeping.xray import XrayManager, _direct_tun_http_probe

ROOT = Path(__file__).resolve().parents[1]


def test_post_start_worker_trusts_completed_xray_startup_transaction() -> None:
    source = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
    function = source[source.index("def _tunnel_passes_real_traffic"):source.index("\n\nclass TaskThread")]
    assert 'getattr(manager, "startup_verified", False)' in function
    assert "return True" in function
    assert "is_any_url_reachable_parallel" not in function
    assert "for wait in" not in function


def test_legacy_live_tun_fallback_does_not_turn_endpoint_filtering_into_disconnect() -> None:
    source = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
    function = source[source.index("def _tunnel_passes_real_traffic"):source.index("\n\nclass TaskThread")]
    assert 'startswith("tun:")' in function
    assert "manager.connected_ping(timeout=1.8)" in function


def test_direct_tun_probe_uses_total_budget_and_diverse_https_endpoints() -> None:
    source = (ROOT / "dicodeping/xray.py").read_text(encoding="utf-8")
    assert "https://www.google.com/generate_204" in source
    assert "https://www.gstatic.com/generate_204" in source
    assert "https://cp.cloudflare.com/generate_204" in source
    assert "is a total budget" in source


def test_connected_ping_preserves_recent_measurement_during_endpoint_flap() -> None:
    manager = XrayManager()
    manager.process = type("P", (), {"poll": lambda self: None})()
    manager.route_mode = "tun:dicodePing-TUN"
    manager._startup_verified = True
    manager._startup_evidence = "tun-http"
    manager._last_verified_ping_ms = 77
    manager._last_verified_at = __import__("time").monotonic()
    with patch("dicodeping.xray._direct_tun_http_probe", return_value=None),          patch.object(manager, "_tun_activity_observed", return_value=True):
        assert manager.connected_ping(timeout=0.6) == 77


def test_startup_source_accepts_real_tun_traffic_or_verified_xray_route() -> None:
    source = (ROOT / "dicodeping/xray.py").read_text(encoding="utf-8")
    start = source[source.index("    def start("):source.index("    def traffic_stats(")]
    assert 'evidence = "tun-traffic"' in start
    assert 'evidence = "tun-http"' in start
    assert 'evidence = "xray-socks+configured-tun"' in start
    assert "No credible Xray/TUN startup evidence" in start
    assert "System TUN route validation failed" not in start
