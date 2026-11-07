#!/usr/bin/env python3
import copy
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("website_release", ROOT / "scripts/verify-website-release.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class WebsiteReleaseTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "web/index.html").read_text()
        self.tag = "v5.0.1"
        self.release = dict(tag_name=self.tag, draft=False, prerelease=False, assets=[
            dict(name=f"DicodePing-5.0.1-{suffix}", size=100,
                 browser_download_url=f"https://github.com/mcodersir/dicodePing/releases/download/v5.0.1/DicodePing-5.0.1-{suffix}")
            for suffix in re.findall(r'data-asset="([^"]+)"', self.html)
        ])

    def test_complete_release(self):
        CHECK.verify(self.release, self.tag, self.html)

    def test_incomplete_or_unpublished_release(self):
        for name, mutate in [
            ("missing package", lambda r: r["assets"].pop()),
            ("draft", lambda r: r.update(draft=True)),
            ("prerelease", lambda r: r.update(prerelease=True)),
            ("wrong tag", lambda r: r.update(tag_name="v5.0.0")),
            ("empty package", lambda r: r["assets"][0].update(size=0)),
            ("wrong URL", lambda r: r["assets"][0].update(browser_download_url="https://example.test/a"))
        ]:
            with self.subTest(name=name):
                release = copy.deepcopy(self.release)
                mutate(release)
                with self.assertRaises(ValueError):
                    CHECK.verify(release, self.tag, self.html)

    def test_stale_page(self):
        with self.assertRaises(ValueError):
            CHECK.verify(self.release, self.tag, self.html.replace("/v5.0.1/", "/v5.0.0/"))


if __name__ == "__main__":
    unittest.main()
