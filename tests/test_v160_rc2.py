"""Tests for the v1.6.0-rc.2 scanner rewrite and real-volume feature."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V160Rc2Tests(unittest.TestCase):
    def test_version_bumped_to_rc2(self) -> None:
        constants = (ROOT / "dicodeping/constants.py").read_text(encoding="utf-8")
        gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text(encoding="utf-8")
        linux_builder = (ROOT / "tools/build_linux.py").read_text(encoding="utf-8")
        self.assertIn('RELEASE_VERSION = "1.6.0-rc.2"', constants)
        self.assertIn('versionCode = 25', gradle)
        self.assertIn('versionName = "1.6.0"', gradle)
        self.assertIn('1.6.0-rc.2', gradle)
        self.assertIn('RC_VERSION = "rc.2"', linux_builder)

    def test_channels_file_is_bundled(self) -> None:
        channels = ROOT / "assets" / "channels.txt"
        self.assertTrue(channels.exists(), msg="assets/channels.txt is missing")
        text = channels.read_text(encoding="utf-8")
        # Each non-comment, non-blank line is a channel username.
        usernames = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        self.assertGreater(len(usernames), 100, msg="channels.txt should contain at least 100 channels")
        # None of the entries should start with http or t.me (we strip that in code).
        for name in usernames[:20]:
            self.assertFalse(name.lower().startswith(("http://", "https://", "t.me/")),
                             msg=f"Channel {name!r} should be a bare username, not a URL")

    def test_crawler_module_is_present(self) -> None:
        crawler = (ROOT / "dicodeping/crawler.py").read_text(encoding="utf-8")
        self.assertIn("def crawl_telegram_channels(", crawler)
        self.assertIn("def fetch_channel(", crawler)
        self.assertIn("def extract_configs(", crawler)
        self.assertIn("def load_channels(", crawler)
        self.assertIn("CONFIG_REGEXES", crawler)
        # Both t.me and telegram.me fallback hosts are tried.
        self.assertIn("https://t.me/s/", crawler)
        self.assertIn("https://telegram.me/s/", crawler)
        # Config regexes cover the protocols that dicodePing can probe.
        self.assertIn("vmess", crawler)
        self.assertIn("vless", crawler)
        self.assertIn("trojan", crawler)
        self.assertIn("ss", crawler)

    def test_scanner_uses_crawler_and_creates_user_source(self) -> None:
        scanner = (ROOT / "dicodeping/scanner.py").read_text(encoding="utf-8")
        # The scanner must call the crawler (not just the default subscription).
        self.assertIn("from .crawler import crawl_telegram_channels, load_channels", scanner)
        self.assertIn("crawl_telegram_channels(", scanner)
        # The scanner must persist survivors as a new user source.
        self.assertIn("SourceDefinition(", scanner)
        self.assertIn("sources_list.append(", scanner)
        # Hard-coded profile lives in the module, not the UI.
        self.assertIn("SCAN_CRAWL_WORKERS", scanner)
        self.assertIn("SCAN_PROBE_WORKERS", scanner)
        self.assertIn("SCAN_PROBE_TIMEOUT_S", scanner)
        # Public API is stable.
        self.assertIn("def run_scan(", scanner)
        self.assertIn("def generate_sub_name(", scanner)
        self.assertIn("def copy_all_servers(", scanner)
        self.assertIn("def export_subscription(", scanner)
        self.assertIn("def list_scanner_subs(", scanner)

    def test_volume_module_reads_real_subscription_header(self) -> None:
        volume = (ROOT / "dicodeping/volume.py").read_text(encoding="utf-8")
        self.assertIn("Subscription-Userinfo", volume)
        self.assertIn("def parse_subscription_userinfo(", volume)
        self.assertIn("def fetch_subscription_quota(", volume)
        self.assertIn("def fetch_live_volumes(", volume)
        self.assertIn("class SubscriptionQuota", volume)
        # The cached quota is keyed by source URL.
        self.assertIn("def cache_quota(", volume)
        self.assertIn("def get_cached_quota(", volume)
        # Backwards-compatible remark heuristic is still present as fallback.
        self.assertIn("def detect_volume_from_name(", volume)
        # Auto-disconnect timer is still present.
        self.assertIn("VOLUME_AUTO_DISCONNECT_SECONDS = 60 * 60", volume)
        self.assertIn("class VolumeAutoDisconnect", volume)
        # Quality rating is still present.
        self.assertIn("def rate_quality(", volume)

    def test_volume_fetch_thread_passes_source_urls(self) -> None:
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
        self.assertIn("class VolumeFetchThread(QThread)", workers)
        self.assertIn("source_urls: dict[str, str] | None = None", workers)
        self.assertIn("source_urls=self.source_urls", workers)

    def test_scanner_thread_accepts_custom_name(self) -> None:
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
        self.assertIn("custom_name: str | None = None", workers)
        self.assertIn("custom_name=self.custom_name", workers)

    def test_i18n_keys_for_rc2_exist(self) -> None:
        i18n = (ROOT / "dicodeping/i18n.py").read_text(encoding="utf-8")
        for key in (
            "scanner_crawl",
            "scanner_name_prompt",
            "scanner_name_placeholder",
            "scanner_volume_real",
            "scanner_volume_remaining",
            "volume_real_fetched",
        ):
            self.assertIn(f'"{key}":', i18n, msg=f"Missing i18n key: {key}")

    def test_scanner_ui_is_minimal_and_supports_custom_name(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        # The big primary button is full-width (no QHBoxLayout wrapping it).
        self.assertIn("self.scanner_run_button.setMinimumHeight(54)", ui)
        # Custom-name input is wired.
        self.assertIn("self.scanner_name_edit", ui)
        self.assertIn("custom_name=custom_name or None", ui)
        # The volume-fetch button sends source_urls.
        self.assertIn("VolumeFetchThread(self.servers, source_urls=source_urls)", ui)
        # After a successful scan, the new source appears on the Servers page.
        self.assertIn("self.render_subscription_list()", ui)
        # The crawler module is wired (not the old bootstrap subscription).
        self.assertIn("scanner_crawl", ui)


if __name__ == "__main__":
    unittest.main()
