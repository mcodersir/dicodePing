"""Capture the RC2 desktop visual matrix with Qt's offscreen backend."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dicodeping-ui-"))
os.environ.setdefault("XDG_CONFIG_HOME", os.environ["APPDATA"])
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dicodeping.models import ServerRecord  # noqa: E402
from dicodeping.rc2_runtime import install_rc2_patches  # noqa: E402
from dicodeping.rc3_runtime import install_rc3_patches  # noqa: E402
from dicodeping.rc4_runtime import install_rc4_patches  # noqa: E402
from dicodeping.rc5_runtime import install_rc5_patches  # noqa: E402
from dicodeping.rc6_runtime import install_rc6_patches  # noqa: E402
from dicodeping.rc7_runtime import install_rc7_patches  # noqa: E402
from dicodeping.rc8_runtime import install_rc8_patches  # noqa: E402
from dicodeping.rc9_runtime import install_rc9_patches  # noqa: E402

for install in (
    install_rc2_patches,
    install_rc3_patches,
    install_rc4_patches,
    install_rc5_patches,
    install_rc6_patches,
    install_rc7_patches,
    install_rc8_patches,
    install_rc9_patches,
):
    install()

from dicodeping.ui import MainWindow  # noqa: E402


def sample_servers() -> list[ServerRecord]:
    cities = (("DE", "Germany", "Frankfurt"), ("FI", "Finland", "Helsinki"), ("NL", "Netherlands", "Amsterdam"))
    return [
        ServerRecord(
            id=f"sample-{index}",
            name=f"Development gateway {index + 1}",
            protocol="VLESS",
            host=f"edge-{index + 1}.example.net",
            port=443,
            config_blob="dmxlc3M6Ly9zYW1wbGU=",
            ping_ms=82 + index * 37,
            ip=f"203.0.113.{index + 10}",
            country=country,
            country_code=code,
            city=city,
            status="online",
            favorite=index == 0,
            source_name="Primary source",
        )
        for index, (code, country, city) in enumerate(cities)
    ]


def main() -> int:
    output = ROOT / "docs/screenshots/v1.8.0-rc.2"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for font_file in (ROOT / "assets" / "fonts").glob("Vazirmatn-*.ttf"):
        QFontDatabase.addApplicationFont(str(font_file))
    app.setFont(QFont("Vazirmatn", 10))
    pages = ("home", "servers", "scanner", "settings", "about")
    sizes = {"compact": (680, 720), "medium": (1000, 760), "expanded": (1440, 900)}
    for language in ("fa", "en"):
        for theme in ("dark", "light"):
            settings = {
                "accepted_disclaimer": True,
                "language": language,
                "language_explicitly_selected": True,
                "theme": theme,
                "reduced_motion": True,
            }
            window = MainWindow(
                preloaded_servers=sample_servers(),
                preloaded_settings=settings,
                startup_prepared=True,
            )
            window.setWindowOpacity(1)
            window.show()
            for size_name, (width, height) in sizes.items():
                window.resize(width, height)
                app.processEvents()
                for page_index, page in enumerate(pages):
                    window.switch_page(page_index, animate=False)
                    app.processEvents()
                    target = output / f"{page}-{language}-{theme}-{size_name}.png"
                    if not window.grab().save(str(target), "PNG"):
                        raise RuntimeError(f"Could not save {target}")
            window.close()
            app.processEvents()
    print(f"Captured {len(list(output.glob('*.png')))} screenshots in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
