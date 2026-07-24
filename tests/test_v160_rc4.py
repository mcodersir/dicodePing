"""Tests for the v1.6.0-rc.4 staged scanner automation, source-scoped
actions, ping cache, and icon-only volume button."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V160Rc4Tests(unittest.TestCase):
    def test_version_bumped_to_rc4(self) -> None:
        constants = (ROOT / "dicodeping/constants.py").read_text(encoding="utf-8")
        gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text(encoding="utf-8")
        linux_builder = (ROOT / "tools/build_linux.py").read_text(encoding="utf-8")
        self.assertIn('RELEASE_VERSION = "1.7.0-rc.', constants)
        self.assertIn("versionCode = 29", gradle)
        self.assertIn('versionName = "1.7.0"', gradle)
        self.assertIn('1.7.0-rc.', gradle)
        self.assertIn('RC_VERSION = "rc.', linux_builder)

    def test_ping_cache_module_is_present(self) -> None:
        cache = (ROOT / "dicodeping/ping_cache.py").read_text(encoding="utf-8")
        self.assertIn("CACHE_TTL_SECONDS = 20 * 60", cache)
        self.assertIn("class CachedPing", cache)
        self.assertIn("def read_cache(", cache)
        self.assertIn("def is_fresh(", cache)
        self.assertIn("def fresh_subset(", cache)
        self.assertIn("def apply_cached_to_records(", cache)
        self.assertIn("def update_cache(", cache)
        self.assertIn("def clear_cache(", cache)

    def test_service_has_refresh_saved_with_cache_and_refresh_subset(self) -> None:
        service = (ROOT / "dicodeping/service.py").read_text(encoding="utf-8")
        self.assertIn("def refresh_saved_with_cache(", service)
        self.assertIn("def refresh_subset(", service)
        self.assertIn("from . import ping_cache", service)
        self.assertIn("ping_cache.apply_cached_to_records(records)", service)
        self.assertIn("ping_cache.update_cache(records)", service)
        self.assertIn("ping_cache.update_cache(fresh)", service)
        self.assertIn("ping_cache.update_cache(subset)", service)

    def test_workers_has_refresh_subset_thread(self) -> None:
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
        self.assertIn("class RefreshSubsetThread(TaskThread):", workers)
        self.assertIn("self.service.refresh_subset(", workers)

    def test_ui_source_scoped_refresh_and_volume(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        # Source-scoped refresh.
        self.assertIn("RefreshSubsetThread(self.service, target_ids, self.language)", ui)
        self.assertIn("self.active_source_id and self.active_source_id != \"all\"", ui)
        # v1.7.0-rc.1: volume fetch and volume button removed.

    def test_scanner_preview_stages_shown_in_ui(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        # Preview lines are shown before the Start button.
        self.assertIn('preview_title = QLabel(self.t("scanner_preview_title"))', ui)
        self.assertIn('preview_line = QLabel(self.t(f"scanner_preview_{i}"))', ui)
        self.assertIn('preview_hint = QLabel(self.t("scanner_preview_hint"))', ui)

    def test_i18n_keys_for_rc4_exist(self) -> None:
        i18n = (ROOT / "dicodeping/i18n.py").read_text(encoding="utf-8")
        for key in (
            "scanner_preview_title",
            "scanner_preview_1",
            "scanner_preview_2",
            "scanner_preview_3",
            "scanner_preview_4",
            "scanner_preview_hint",
        ):
            self.assertIn(f'"{key}":', i18n, msg=f"Missing i18n key: {key}")

    def _skip_test_volume_fetch_has_get_fallback(self) -> None:
        # The volume fetch must fall back to a ranged GET when HEAD is
        # rejected by the provider — otherwise it can never extract the
        # real Subscription-Userinfo header for many providers.
        volume = (ROOT / "dicodeping/volume.py").read_text(encoding="utf-8")
        self.assertIn('def _try(method: str, *, add_range: bool = False)', volume)
        self.assertIn('header_value = _try("HEAD")', volume)
        self.assertIn('header_value = _try("GET", add_range=True)', volume)
        self.assertIn('request.add_header("Range", "bytes=0-0")', volume)

    def test_android_source_scoped_actions(self) -> None:
        repo = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt").read_text(encoding="utf-8")
        self.assertIn("fun pingSource(sourceId: String)", repo)
        servers = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ServersFragment.kt").read_text(encoding="utf-8")
        self.assertIn("vm.repo.pingSource(sourceId)", servers)
        self.assertIn("targetServers = allServers.filter { it.sourceId == sourceId }", servers)
        # Android volume button is icon-only (44dp, no text).
        layout = (ROOT / "dicodePing_android/app/src/main/res/layout/fragment_servers.xml").read_text(encoding="utf-8")
        self.assertIn('android:id="@+id/fetchVolumes"', layout)
        self.assertIn('android:layout_width="44dp"', layout)
        self.assertIn('android:contentDescription="@string/volume_fetch"', layout)

    def test_android_scanner_preview_shown(self) -> None:
        layout = (ROOT / "dicodePing_android/app/src/main/res/layout/fragment_scanner.xml").read_text(encoding="utf-8")
        self.assertIn('@string/scanner_preview_title', layout)
        self.assertIn('@string/scanner_preview_1', layout)
        self.assertIn('@string/scanner_preview_2', layout)
        self.assertIn('@string/scanner_preview_3', layout)
        self.assertIn('@string/scanner_preview_4', layout)
        self.assertIn('@string/scanner_preview_hint', layout)
        self.assertIn('@string/scanner_start', layout)


if __name__ == "__main__":
    unittest.main()
