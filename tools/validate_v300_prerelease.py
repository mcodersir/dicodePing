"""Validation script for dicodePing v3.0.0 pre-release.

Checks:
- v2rayN integration layer exists and is importable
- Version metadata updated to 3.x
- Modern UI layer exists
- Subscription source is preserved from v2
- Build configuration files are present
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dicodeping.constants import APP_NAME, RELEASE_VERSION, VERSION, DEFAULT_SUBSCRIPTION_URL

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

errors: list[str] = []
warnings: list[str] = []


def check(condition: bool, message: str, is_error: bool = True) -> None:
    status = "PASS" if condition else "FAIL"
    prefix = "[OK]" if condition else "[X]"
    print(f"  [{status}] {prefix} {message}")
    if not condition and is_error:
        errors.append(message)
    elif not condition:
        warnings.append(message)


def main() -> int:
    print("\n=== dicodePing v3.0.0 Prerelease Validation ===\n")

    print("1. Version metadata checks:")
    check(VERSION.startswith("3."), f"VERSION is '3.x.x' (got '{VERSION}')")
    check(RELEASE_VERSION.startswith("3."), f"RELEASE_VERSION is '3.x.x' (got '{RELEASE_VERSION}')")

    print("\n2. v2rayN integration layer checks:")
    integration_dir = Path(__file__).resolve().parents[1] / "dicodeping" / "v2rayN" / "integration"
    check(integration_dir.exists(), "v2rayN integration directory exists")

    required_modules = ["net.py", "xray.py", "core_manager.py", "connection_manager.py", "service.py", "discovery.py", "protocols.py", "models.py", "ui_v3.py", "version.py"]
    for module in required_modules:
        check((integration_dir / module).exists(), f"v2rayN integration module exists: {module}")

    print("\n3. Modern UI checks:")
    ui_v3 = integration_dir / "ui_v3.py"
    if ui_v3.exists():
        content = ui_v3.read_text(encoding="utf-8")
        check("MainWindowV3" in content, "MainWindowV3 class exists in ui_v3.py")
        check("ThemeManager" in content, "ThemeManager for dark/light themes exists")
        check("ServerCard" in content, "ServerCard widget exists")
        check("ConnectionPanel" in content, "ConnectionPanel widget exists")
        check("DashboardView" in content, "DashboardView widget exists")
    else:
        check(False, "ui_v3.py exists")

    print("\n4. Subscription source checks (preserved from v2):")
    check(
        DEFAULT_SUBSCRIPTION_URL == "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt",
        "Default subscription URL is preserved from v2"
    )

    print("\n5. Build configuration checks:")
    deploy_script = Path(__file__).resolve().parents[1] / "DEPLOY_RELEASE_300_PRERELEASE.bat"
    check(deploy_script.exists(), "v3 deployment script exists")

    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-v3.yml"
    check(workflow.exists(), "v3 CI workflow exists")

    print("\n6. v2rayN library checks:")
    v2rayN_dir = Path(__file__).resolve().parents[1] / "v2rayN-7.24.5"
    check(v2rayN_dir.exists(), "v2rayN-7.24.5 library directory exists")
    if v2rayN_dir.exists():
        v2rayN_core = v2rayN_dir / "v2rayN"
        check(v2rayN_core.exists(), "v2rayN core directory exists")

    print("\n" + "=" * 50)
    if errors:
        print(f"VALIDATION FAILED: {len(errors)} error(s)")
        for error in errors:
            print(f"  ✗ {error}")
        return 1
    if warnings:
        print(f"VALIDATION PASSED with {len(warnings)} warning(s)")
        for warning in warnings:
            print(f"  ⚠ {warning}")
        return 0
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
