from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]



def _load_sampler():
    source = (ROOT / "dicodeping/rc7_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "_sample_records_by_source")
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"defaultdict": defaultdict, "hashlib": hashlib, "math": math}
    exec(compile(module, "rc7_sampler", "exec"), namespace)
    return namespace["_sample_records_by_source"]


def _row(source: str, index: int):
    return SimpleNamespace(id=f"{source}-{index}", source_id=source)


class V190Rc7Tests(unittest.TestCase):
    def test_splash_samples_thirty_percent_per_source(self) -> None:
        records = [_row("a", i) for i in range(10)] + [_row("b", i) for i in range(3)]
        sampler = _load_sampler()
        sampled = sampler(records, 0.30)
        counts = Counter(item.source_id for item in sampled)
        self.assertEqual(counts, {"a": 3, "b": 1})
        self.assertEqual(
            [item.id for item in sampled],
            [item.id for item in sampler(records, 0.30)],
        )

    def test_scanner_compares_numeric_latency_not_result_objects(self) -> None:
        scanner = (ROOT / "dicodeping/scanner.py").read_text(encoding="utf-8")
        pick = scanner.split("def _connect_best_server", 1)[1].split("def run_scan", 1)[0]
        self.assertIn("int(quality.ping_ms)", pick)
        self.assertIn("verified.sort(key=lambda row: row[0])", pick)
        self.assertNotIn("verified.append((quality,", pick)

    def test_dashboard_auto_connect_has_a_real_selection_worker(self) -> None:
        runtime = (ROOT / "dicodeping/rc7_runtime.py").read_text(encoding="utf-8")
        workers = (ROOT / "dicodeping/workers.py").read_text(encoding="utf-8")
        connect = runtime.split("def connect_best(self):", 1)[1].split("def save(self):", 1)[0]
        self.assertIn("BestServerSelectionThread", connect)
        self.assertIn("self.connect_server", connect)
        self.assertIn("class BestServerSelectionThread", workers)
        self.assertIn("test_config", workers)

    def test_sidebar_is_explicitly_placed_and_aligned(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        body = ui.split("# Do not rely on QApplication RTL mirroring", 1)[1].split("def _page_header", 1)[0]
        self.assertIn("if self.is_rtl:", body)
        self.assertIn("self.body_layout.addWidget(content, 1)", body)
        self.assertIn("self.body_layout.addWidget(self.sidebar, 0)", body)
        alignment = ui.split("def _apply_button_alignment", 1)[1].split("def _request_page", 1)[0]
        self.assertIn("button.setLayoutDirection(direction)", alignment)
        self.assertIn("Qt.ToolButtonTextBesideIcon", alignment)

    def test_settings_use_available_height_and_combo_has_arrow(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        self.assertIn("methods_tab_layout.addWidget(self._build_connection_methods_section(), 1)", ui)
        self.assertIn("sharing_tab_layout.addWidget(self._build_vpn_sharing_section(), 1)", ui)
        self.assertIn("layout.insertWidget(1, settings_body, 1)", ui)
        self.assertIn("QComboBox::down-arrow", ui)
        self.assertTrue((ROOT / "assets/chevron-down.svg").is_file())

    def test_doh_is_disabled_by_default_on_desktop_and_android(self) -> None:
        ui = (ROOT / "dicodeping/ui.py").read_text(encoding="utf-8")
        android = (
            ROOT
            / "dicodePing_android/app/src/main/java/ir/dicode/ping/data/SettingsStore.kt"
        ).read_text(encoding="utf-8")
        self.assertIn('self.settings.get("secure_dns_doh", False)', ui)
        self.assertIn('prefs.getBoolean("secure_dns_doh", false)', android)

    def test_rc7_release_payload_is_complete(self) -> None:
        workflow = (ROOT / ".github/workflows/v1.9.0-rc.10-release.yml").read_text(encoding="utf-8")
        for name in (
            "dicodePing-v1.9.0-rc.10-windows-x64.exe",
            "dicodePing-v1.9.0-rc.10-linux-x86_64.tar.gz",
            "dicodePing-v1.9.0-rc.10-macos-${{ matrix.architecture }}.dmg",
            "dicodePing-v1.9.0-rc.10-android.apk",
        ):
            self.assertIn(name, workflow)
        self.assertTrue((ROOT / "docs/releases/v1.9.0-rc.10.md").is_file())
        self.assertTrue((ROOT / "DEPLOY_PRERELEASE_RC10.bat").is_file())


if __name__ == "__main__":
    unittest.main()
