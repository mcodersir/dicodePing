from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path

from dicodeping.models import ServerRecord
from dicodeping.protocols import extract_configs, parse_endpoint
from dicodeping.rc2_core import extract_display_name
from dicodeping.rc7_core import batches, diverse_auto_candidates


class Rc7Tests(unittest.TestCase):
    def test_fragment_is_the_display_name(self) -> None:
        self.assertEqual(extract_display_name("vless://id@example.com:443#My%20Fast%20Server"), "My Fast Server")

    def test_vmess_fragment_wins_over_internal_label(self) -> None:
        payload = base64.urlsafe_b64encode(json.dumps({"add": "example.com", "port": "443", "ps": "Old Name"}).encode()).decode().rstrip("=")
        self.assertEqual(extract_display_name(f"vmess://{payload}#Public%20Name"), "Public Name")
        self.assertIsNotNone(parse_endpoint(f"vmess://{payload}#Public%20Name"))

    def test_encoded_spaces_do_not_truncate_config(self) -> None:
        raw = "vless://id@example.com:443#A%20Long%20Name"
        self.assertEqual(extract_configs(raw), [raw])

    def test_batches_preserve_order(self) -> None:
        self.assertEqual(list(batches(list(range(7)), 3)), [[0, 1, 2], [3, 4, 5], [6]])

    def test_auto_candidates_are_ranked_and_endpoint_diverse(self) -> None:
        rows = [
            ServerRecord(id="a", name="A", protocol="VLESS", host="one.example", port=443, config_blob="a", ping_ms=40, status="online"),
            ServerRecord(id="b", name="B", protocol="VLESS", host="one.example", port=443, config_blob="b", ping_ms=20, status="online"),
            ServerRecord(id="c", name="C", protocol="VLESS", host="two.example", port=443, config_blob="c", ping_ms=30, status="online"),
        ]
        result = diverse_auto_candidates(rows, limit=3)
        self.assertEqual([row.id for row in result], ["b", "c"])

    def test_favorite_does_not_override_a_better_automatic_server(self) -> None:
        rows = [
            ServerRecord(id="favorite", name="Favorite", protocol="VLESS", host="one.example", port=443, config_blob="a", ping_ms=140, status="online", favorite=True),
            ServerRecord(id="fast", name="Fast", protocol="VLESS", host="two.example", port=443, config_blob="b", ping_ms=80, status="online"),
        ]
        self.assertEqual(diverse_auto_candidates(rows, limit=2)[0].id, "fast")

    def test_auto_retry_uses_different_resolved_networks(self) -> None:
        rows = [
            ServerRecord(id="a", name="A", protocol="VLESS", host="one.example", port=443, config_blob="a", ping_ms=80, ip="1.2.3.4", status="online"),
            ServerRecord(id="b", name="B", protocol="VLESS", host="alias.example", port=8443, config_blob="b", ping_ms=85, ip="1.2.3.4", status="online"),
            ServerRecord(id="c", name="C", protocol="VLESS", host="two.example", port=443, config_blob="c", ping_ms=90, ip="5.6.7.8", status="online"),
        ]
        self.assertEqual([row.id for row in diverse_auto_candidates(rows, limit=3)], ["a", "c"])

    def test_server_list_uses_direct_icmp_once_per_host(self) -> None:
        runtime = (Path(__file__).resolve().parents[1] / "dicodeping" / "rc7_runtime.py").read_text(encoding="utf-8")
        test_records = runtime.split("def _test_records", 1)[1].split("\ndef _apply_geo", 1)[0]
        self.assertIn("net_module.ping_many", test_records)
        self.assertIn("dict.fromkeys(row.host for row in rows)", test_records)
        self.assertNotIn("probe_outbound_delay", test_records)

    def test_auto_selection_keeps_the_70ms_and_location_rules(self) -> None:
        runtime = (Path(__file__).resolve().parents[1] / "dicodeping" / "rc7_runtime.py").read_text(encoding="utf-8")
        candidates = runtime.split("def auto_candidates", 1)[1].split("\n    service_module.ServerService", 1)[0]
        self.assertIn("MIN_TRUSTED_AUTO_PING_MS", candidates)
        self.assertIn("is_restricted_location", candidates)


if __name__ == "__main__":
    unittest.main()
