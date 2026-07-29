from __future__ import annotations

import base64
import json
import unittest

from dicodeping.rc2_core import (
    choose_conservative_latency,
    extract_display_name,
    infer_country_hint,
    is_generated_or_unknown_name,
)


class Rc2Tests(unittest.TestCase):
    def test_extracts_url_fragment_name(self) -> None:
        raw = "vless://id@example.com:443?security=tls#%F0%9F%87%A9%F0%9F%87%AA%20Frankfurt%20Premium"
        self.assertEqual(extract_display_name(raw), "🇩🇪 Frankfurt Premium")

    def test_extracts_vmess_ps_name(self) -> None:
        payload = {"v": "2", "ps": "Amsterdam 01", "add": "example.com", "port": "443", "id": "id"}
        raw = "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()
        self.assertEqual(extract_display_name(raw), "Amsterdam 01")

    def test_unknown_names_are_rejected(self) -> None:
        self.assertEqual(extract_display_name("trojan://pass@example.com:443#نامشخص"), "")
        self.assertTrue(is_generated_or_unknown_name("سرور Germany • 01"))

    def test_country_hint_from_flag(self) -> None:
        self.assertEqual(infer_country_hint("🇳🇱 Amsterdam"), ("NL", "Netherlands"))

    def test_latency_is_conservative(self) -> None:
        self.assertEqual(choose_conservative_latency((7, 104)), 104)
        self.assertIsNone(choose_conservative_latency((None, None)))


if __name__ == "__main__":
    unittest.main()
