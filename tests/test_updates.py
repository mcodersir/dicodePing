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


if __name__ == "__main__":
    unittest.main()
