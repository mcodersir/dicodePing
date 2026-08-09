"""Unit tests for dicodePing Version 3 pre-release (v3.0.0-pre.1)."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dicodeping.constants import (
    APP_ID,
    APP_NAME,
    VERSION,
    RELEASE_VERSION,
    DEFAULT_SUBSCRIPTION_URL,
)


def test_v300_version_metadata() -> None:
    """Verify Version 3 metadata is consistent across package files."""
    assert VERSION == "3.0.0"
    assert RELEASE_VERSION == "3.0.0-rc.1"
    assert APP_NAME == "dicodePing"
    assert APP_ID == "ir.dicode.dicodePing"


def test_v300_subscription_source() -> None:
    """Verify the default subscription source is preserved from v2."""
    expected_url = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt"
    assert DEFAULT_SUBSCRIPTION_URL == expected_url


def test_v300_v2rayn_integration_imports() -> None:
    """Verify v2rayN integration layer imports cleanly."""
    from dicodeping.v2rayN.integration import (
        ConnectionManager,
        ServerService,
        XrayManager,
        resolve_ipv4,
        is_url_reachable,
    )
    assert ConnectionManager is not None
    assert ServerService is not None
    assert XrayManager is not None


def test_v300_modern_ui_classes() -> None:
    """Verify modern UI components exist in ui_v3.py."""
    from dicodeping.v2rayN.integration.ui_v3 import (
        MainWindowV3,
        ThemeManager,
        ServerCard,
        ConnectionPanel,
        DashboardView,
        StatusBar,
        SidebarNav,
        theme_manager,
    )
    assert MainWindowV3 is not None
    assert ThemeManager is not None
    assert ServerCard is not None
    assert ConnectionPanel is not None
    assert DashboardView is not None
    assert StatusBar is not None
    assert SidebarNav is not None
    assert theme_manager is not None


def test_v300_desktop_builders_metadata() -> None:
    """Verify all desktop build scripts reference app_v3.py and version 3.0.0-rc.1."""
    for script_name in ("build_windows.py", "build_linux.py", "build_macos.py"):
        content = (ROOT / "tools" / script_name).read_text(encoding="utf-8")
        assert 'APP_VERSION = "3.0.0-rc.1"' in content
        assert "app_v3.py" in content


def test_v300_android_metadata() -> None:
    """Verify Android Gradle configuration targets version 3.0.0-rc.1."""
    gradle_file = ROOT / "dicodePing_android" / "app" / "build.gradle.kts"
    content = gradle_file.read_text(encoding="utf-8")
    assert 'versionName = "3.0.0-rc.1"' in content
    assert 'buildConfigField("String", "RELEASE_VERSION", "\\"3.0.0-rc.1\\"")' in content
