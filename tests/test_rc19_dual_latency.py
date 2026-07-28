from pathlib import Path
from unittest.mock import patch

from dicodeping.config_checker import test_config as run_config_test
from dicodeping.models import ServerRecord

ROOT = Path(__file__).resolve().parents[1]

def test_server_record_migrates_legacy_icmp_to_tcp():
    row = ServerRecord.from_dict({
        "id":"1", "name":"x", "protocol":"VLESS", "host":"example.com", "port":443,
        "config_blob":"x", "icmp_ms":31, "ping_ms":74,
    })
    assert row.tcp_ms == 31
    assert row.ping_ms == 74


def test_config_checker_runs_one_tcp_and_one_xray():
    raw = "vless://00000000-0000-0000-0000-000000000000@example.com:443?security=tls&type=tcp#x"
    with patch("dicodeping.config_checker._tcp_connect_delay", return_value=(18, "")) as tcp,          patch("dicodeping.config_checker.build_xray_outbound", return_value={"protocol":"vless"}),          patch("dicodeping.config_checker.probe_outbound_delay", return_value=67) as xray:
        result = run_config_test(raw, attempts=5, min_success=4)
    assert result.ok is True
    assert result.tcp_ms == 18
    assert result.ping_ms == 67
    assert result.attempts == 1
    assert result.success_count == 1
    assert tcp.call_count == 1
    assert xray.call_count == 1


def test_tcp_success_without_xray_is_not_healthy():
    raw = "vless://00000000-0000-0000-0000-000000000000@example.com:443?security=tls&type=tcp#x"
    with patch("dicodeping.config_checker._tcp_connect_delay", return_value=(12, "")),          patch("dicodeping.config_checker.build_xray_outbound", return_value={"protocol":"vless"}),          patch("dicodeping.config_checker.probe_outbound_delay", return_value=None):
        result = run_config_test(raw)
    assert result.tcp_ms == 12
    assert result.ping_ms is None
    assert result.ok is False


def test_desktop_table_has_separate_latency_columns():
    ui = (ROOT / "dicodeping/ui.py").read_text("utf-8")
    assert "QTableWidget(0, 9)" in ui
    assert 'self.t("tcp_ping")' in ui
    assert 'self.t("xray_ping")' in ui
    assert "setCellWidget(row, 4, tcp_badge)" in ui
    assert "setCellWidget(row, 5, xray_badge)" in ui
