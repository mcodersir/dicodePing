from __future__ import annotations

import threading
import unittest
from unittest import mock
from pathlib import Path

from dicodeping.resource_tuning import build_resource_profile, current_resource_profile
from dicodeping.xray import build_tun_config, probe_outbound_delay


RAW = (
    "vless://11111111-1111-1111-1111-111111111111@example.com:443"
    "?security=tls&type=tcp#rc4"
)
ROOT = Path(__file__).resolve().parents[1]


class AdaptiveRuntimeTests(unittest.TestCase):
    def test_router_profile_is_bounded(self) -> None:
        profile = build_resource_profile(cpu_count=1, memory_bytes=512 * 1024 * 1024)
        self.assertEqual(profile.crawl_workers, 2)
        self.assertLessEqual(profile.probe_workers, 4)
        self.assertLessEqual(profile.ping_workers, 8)
        self.assertLessEqual(profile.internal_queue_limit, 32)

    def test_desktop_profile_scales_without_unbounded_queues(self) -> None:
        profile = build_resource_profile(cpu_count=32, memory_bytes=64 * 1024**3)
        self.assertLessEqual(profile.probe_workers, 48)
        self.assertLessEqual(profile.ping_workers, 64)
        self.assertLessEqual(profile.internal_queue_limit, 192)

    def test_xray_policy_uses_detected_buffer_limit(self) -> None:
        config = build_tun_config(RAW)
        expected = current_resource_profile().network_buffer_kib
        self.assertEqual(config["policy"]["levels"]["0"]["bufferSize"], expected)

    def test_cancelled_probe_never_starts_xray(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        with mock.patch("dicodeping.xray.ensure_xray", side_effect=AssertionError("must not start")):
            self.assertIsNone(probe_outbound_delay(RAW, cancel_event=cancelled))

    def test_android_scanner_persists_and_probes_discovered_configs(self) -> None:
        scanner = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt").read_text(encoding="utf-8")
        repository = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt").read_text(encoding="utf-8")
        self.assertIn("importScannerConfigs(configs, customName)", scanner)
        self.assertIn("sourceId = sourceId", repository)
        self.assertIn("pingServers(imported)", repository)

    def test_android_header_matches_requested_rtl_brand_layout(self) -> None:
        layout = (ROOT / "dicodePing_android/app/src/main/res/layout/fragment_home.xml").read_text(encoding="utf-8")
        fa = (ROOT / "dicodePing_android/app/src/main/res/values-fa/strings.xml").read_text(encoding="utf-8")
        self.assertIn('android:text="dicodeping"', layout)
        self.assertIn('<string name="brand_title">رفع تحریم\u200cها</string>', fa)


if __name__ == "__main__":
    unittest.main()
