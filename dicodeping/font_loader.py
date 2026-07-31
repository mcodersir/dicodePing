from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QFont, QFontDatabase

from .constants import ASSET_DIR, IS_FROZEN
from .diagnostics import get_logger

LOGGER = get_logger("font")
FONT_FILES = (
    "Vazirmatn-Regular.ttf",
    "Vazirmatn-Medium.ttf",
    "Vazirmatn-Bold.ttf",
)


@dataclass(frozen=True)
class FontLoadResult:
    family: str
    loaded_files: tuple[str, ...]
    missing_files: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.family.casefold() == "vazirmatn" and len(self.loaded_files) == len(FONT_FILES)


def register_vazirmatn() -> FontLoadResult:
    """Register all bundled Vazirmatn weights from bytes.

    Loading from data avoids platform-specific path and extraction problems in
    PyInstaller one-file executables and macOS application bundles.
    """
    font_dir = ASSET_DIR / "fonts"
    loaded: list[str] = []
    missing: list[str] = []
    families: list[str] = []
    for filename in FONT_FILES:
        path = font_dir / filename
        if not path.is_file() or path.stat().st_size < 50_000:
            missing.append(filename)
            continue
        font_id = QFontDatabase.addApplicationFontFromData(QByteArray(path.read_bytes()))
        if font_id < 0:
            missing.append(filename)
            continue
        names = list(QFontDatabase.applicationFontFamilies(font_id))
        families.extend(names)
        loaded.append(filename)

    family = next((name for name in families if name.casefold() == "vazirmatn"), "")
    result = FontLoadResult(family, tuple(loaded), tuple(missing))
    if result.ok:
        LOGGER.info("Bundled Vazirmatn registered: family=%s weights=%s", family, ",".join(loaded))
        return result

    LOGGER.error(
        "Bundled Vazirmatn registration failed: family=%r loaded=%s missing=%s root=%s",
        family,
        loaded,
        missing,
        font_dir,
    )
    if IS_FROZEN:
        raise RuntimeError("فونت داخلی وزیرمتن در بسته برنامه موجود نیست یا توسط Qt ثبت نشد.")
    return result


def application_font(result: FontLoadResult, point_size: int = 10) -> QFont:
    font = QFont(result.family or "Vazirmatn", point_size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font
