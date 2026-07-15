from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dicodeping.updates import find_application_update


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class UpdateTests(unittest.TestCase):
    def test_rc_client_receives_the_next_real_platform_release(self) -> None:
        payload = [
            {
                "tag_name": "v0.1.5-rc.2",
                "name": "Compatibility bridge — dicodePing v0.1.4-rc.7",
                "assets": [],
            },
            {
                "tag_name": "v0.1.4-rc.7",
                "name": "dicodePing v0.1.4-rc.7",
                "html_url": "https://example.test/release",
                "assets": [{"name": "dicodePing-v0.1.4-rc.7-windows.exe", "browser_download_url": "https://example.test/windows.exe"}],
            },
        ]
        with patch("dicodeping.updates.urllib.request.urlopen", return_value=_Response(payload)):
            release = find_application_update("0.1.4-rc.6", "windows")
        self.assertIsNotNone(release)
        self.assertEqual(release.tag, "v0.1.4-rc.7")
        self.assertEqual(release.asset_url, "https://example.test/windows.exe")

    def test_rc7_receives_v015_and_skips_compatibility_bridge(self) -> None:
        payload = [
            {
                "tag_name": "v0.1.6-rc.0",
                "name": "Compatibility bridge — dicodePing v0.1.5-rc.1",
                "assets": [],
            },
            {
                "tag_name": "v0.1.5-rc.1",
                "name": "dicodePing v0.1.5-rc.1",
                "html_url": "https://example.test/v015",
                "assets": [
                    {
                        "name": "dicodePing-v0.1.5-rc.1-linux-x86_64.tar.gz",
                        "browser_download_url": "https://example.test/linux.tar.gz",
                    }
                ],
            },
        ]
        with patch("dicodeping.updates.urllib.request.urlopen", return_value=_Response(payload)):
            release = find_application_update("0.1.4-rc.7", "linux")
        self.assertIsNotNone(release)
        self.assertEqual(release.tag, "v0.1.5-rc.1")
        self.assertEqual(release.asset_url, "https://example.test/linux.tar.gz")


if __name__ == "__main__":
    unittest.main()
