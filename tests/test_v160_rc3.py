"""Tests for the v1.6.0-rc.3 staged scanner, ETA, and visible quality column."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V160Rc3Tests(unittest.TestCase):
    def test_version_bumped_to_rc3(self) -> None:
        constants = (ROOT / "dicodeping/constants.py").read_text(encoding="utf-8")
        gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text(encoding="utf-8")
        linux_builder = (ROOT / "tools/build_linux.py").read_text(encoding="utf-8")
        # The RC3+ line.  The exact RC suffix changes per release.
        self.assertIn('RELEASE_VERSION = "1.6.0-rc.', constants)
        self.assertIn('versionCode = 2', gradle)  # 26 (rc.3) or 27 (rc.4)
        self.assertIn('versionName = "1.6.0"', gradle)
        self.assertIn('1.6.0-rc.', gradle)
        self.assertIn('RC_VERSION = "rc.', linux_builder)

    def test_eta_helper_module_is_present(self) -> None:
        eta = (ROOT / "dicodeping/eta.py").read_text(encoding="utf-8")
        self.assertIn("class ETAEstimator", eta)
        self.assertIn("def update(", eta)
        self.assertIn("def remaining_seconds(", eta)
        self.assertIn("def progress_percent(", eta)
        self.assertIn("def format_seconds(", eta)

    def test_scanner_is_staged_with_stop_and_alive_count(self) -> None:
        scanner = (ROOT / "dicodeping/scanner.py").read_text(encoding="utf-8")
        # Three-stage pipeline.
        self.assertIn("Stage 1 — Connect", scanner)
        self.assertIn("Stage 2 — Crawl + Probe", scanner)
        self.assertIn("Stage 3 — Save", scanner)
        # Stop event support.
        self.assertIn("stop_event: threading.Event", scanner)
        self.assertIn("state.stop_requested.is_set()", scanner)
        # Live alive-count callback.
        self.assertIn("AliveCountCallback", scanner)
        self.assertIn("alive_count_callback", scanner)
        # Configurable per-channel limits with rank-1 / rank-2 split.
        self.assertIn("DEFAULT_RANK1_PER_CHANNEL = 3", scanner)
        self.assertIn("DEFAULT_RANK2_PER_CHANNEL = 3", scanner)
        self.assertIn("RANK1_CHANNELS", scanner)
        # ETA callback.
        self.assertIn("eta_callback", scanner)
        # Connect / disconnect callbacks for the bootstrap TUN.
        self.assertIn("connect_callback", scanner)
        self.assertIn("disconnect_callback", scanner)
        # stopped_early flag on the result.
        self.assertIn("stopped_early: bool = False", scanner)

    def test_scanner_thread_supports_stop_and_alive_count(self) -> None:
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
        self.assertIn("class ScannerThread(QThread)", workers)
        self.assertIn("alive_count = Signal(int)", workers)
        self.assertIn("eta = Signal(str)", workers)
        self.assertIn("stage_change = Signal(int, str)", workers)
        self.assertIn("def requestStop", workers)
        self.assertIn("rank1_limit", workers)
        self.assertIn("rank2_limit", workers)
        self.assertIn("connect_callback", workers)
        self.assertIn("disconnect_callback", workers)

    def test_i18n_keys_for_rc3_exist(self) -> None:
        i18n = (ROOT / "dicodeping/i18n.py").read_text(encoding="utf-8")
        for key in (
            "scanner_stage1",
            "scanner_stage1_pick",
            "scanner_stage1_connect",
            "scanner_stage1_skip",
            "scanner_stage2",
            "scanner_stage2_crawl",
            "scanner_stage2_probe",
            "scanner_stage3",
            "scanner_no_bootstrap",
            "scanner_no_channels",
            "scanner_no_configs",
            "scanner_no_alive",
            "scanner_no_alive_stopped",
            "scanner_stopped_early",
            "scanner_alive_count",
            "scanner_eta_label",
            "scanner_stop",
            "scanner_start",
            "scanner_rank1_limit",
            "scanner_rank2_limit",
            "scanner_settings_help",
            "eta_label",
            "volume_real_label",
            "quality_label",
        ):
            self.assertIn(f'"{key}":', i18n, msg=f"Missing i18n key: {key}")

    def test_servers_page_has_quality_column_and_volume_button(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        # 8-column table.
        self.assertIn("self.table = QTableWidget(0, 8)", ui)
        # Quality column header uses the new i18n key.
        self.assertIn("self.t(\"quality_label\")", ui)
        # Volume-fetch button on the Servers page toolbar.
        self.assertIn("self.server_volume_button", ui)
        # Info cell renders both quality label and volume label inline.
        self.assertIn("info_text = rating.label_fa", ui)

    def test_scanner_page_has_stage_dots_stop_eta_alive_badges(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        # Three stage dots.
        self.assertIn("for i in range(1, 4):", ui)
        self.assertIn("self.scanner_stage_labels: list[QLabel] = []", ui)
        # Stop button (initially hidden).
        self.assertIn('self.scanner_stop_button = QPushButton(self.t("scanner_stop"))', ui)
        # ETA + alive badges.
        self.assertIn("self.scanner_eta_label", ui)
        self.assertIn("self.scanner_alive_label", ui)
        # Stage-change handler.
        self.assertIn("def _set_scanner_stage_dot", ui)
        self.assertIn("def _scanner_stage_changed", ui)
        # Stop handler.
        self.assertIn("def stop_scanner", ui)
        # Bootstrap connect / disconnect callbacks.
        self.assertIn("def _scanner_connect_bootstrap", ui)
        self.assertIn("def _scanner_disconnect_bootstrap", ui)


if __name__ == "__main__":
    unittest.main()
