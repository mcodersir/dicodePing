"""Stable validation script for dicodePing v3.0.0.

Additional strict checks for the v3 stable release.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dicodeping.constants import APP_NAME, APP_ID, VERSION, RELEASE_VERSION

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

errors: list[str] = []


def check(condition: bool, message: str) -> None:
    status = "PASS" if condition else "FAIL"
    prefix = "[OK]" if condition else "[X]"
    print(f"  [{status}] {prefix} {message}")
    if not condition:
        errors.append(message)


def main() -> int:
    print("\n=== dicodePing v3.0.0 Stable Validation ===\n")

    print("1. Version checks:")
    check(VERSION == "3.0.0", f"VERSION is '3.0.0' (got '{VERSION}')")
    check(RELEASE_VERSION == "3.0.0" or RELEASE_VERSION.startswith("3.0.0"), f"RELEASE_VERSION is '3.0.0' (got '{RELEASE_VERSION}')")
    check(APP_ID == "ir.dicode.dicodePing", f"APP_ID is 'ir.dicode.dicodePing' (got '{APP_ID}')")

    print("\n2. v2rayN integration checks:")
    integration_dir = Path(__file__).resolve().parents[1] / "dicodeping" / "v2rayN" / "integration"
    init_file = integration_dir / "__init__.py"
    check(init_file.exists(), "__init__.py exists in integration package")

    print("\n3. Core compatibility checks:")
    xray_py = integration_dir / "xray.py"
    if xray_py.exists():
        content = xray_py.read_text(encoding="utf-8")
        check("ensure_xray" in content, "ensure_xray function exists")
        check("ensure_wintun" in content, "ensure_wintun function exists")
        check("XrayManager" in content, "XrayManager class exists")
        check("build_tun_config" in content, "build_tun_config function exists")

    print("\n4. Connection manager checks:")
    cm_py = integration_dir / "connection_manager.py"
    if cm_py.exists():
        content = cm_py.read_text(encoding="utf-8")
        check("ConnectionManager" in content, "ConnectionManager class exists")
        check("AlternativeCoreManager" in content, "AlternativeCoreManager exists")
        check("register_warp" in content, "register_warp function exists")

    print("\n5. Service layer checks:")
    service_py = integration_dir / "service.py"
    if service_py.exists():
        content = service_py.read_text(encoding="utf-8")
        check("ServerService" in content, "ServerService class exists")
        check("build_and_save" in content, "build_and_save method exists")
        check("refresh_saved" in content, "refresh_saved method exists")
        check("auto_candidates" in content, "auto_candidates method exists")
        check("best_server" in content, "best_server method exists")

    print("\n6. Modern UI checks:")
    ui_v3 = integration_dir / "ui_v3.py"
    if ui_v3.exists():
        content = ui_v3.read_text(encoding="utf-8")
        check("MainWindowV3" in content, "MainWindowV3 class exists")
        check("DashboardView" in content, "DashboardView class exists")
        check("ServerCard" in content, "ServerCard class exists")
        check("ConnectionPanel" in content, "ConnectionPanel class exists")
        check("StatusBar" in content, "StatusBar class exists")
        check("SidebarNav" in content, "SidebarNav class exists")
        check("ThemeManager" in content, "ThemeManager class exists")
        check("theme_manager" in content, "theme_manager instance exists")

    print("\n" + "=" * 50)
    if errors:
        print(f"STABLE VALIDATION FAILED: {len(errors)} error(s)")
        for error in errors:
            print(f"  ✗ {error}")
        return 1
    print("STABLE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
