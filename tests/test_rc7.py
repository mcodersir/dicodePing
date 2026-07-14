from __future__ import annotations

import base64
import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
