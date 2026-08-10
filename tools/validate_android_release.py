from __future__ import annotations

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dicodePing_android/app"
RES = APP / "src/main/res"


def text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"Not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def main() -> int:
    errors: list[str] = []
    gradle = text("dicodePing_android/app/build.gradle.kts")
    manifest = text("dicodePing_android/app/src/main/AndroidManifest.xml")
    lint_policy = text("dicodePing_android/app/lint.xml")
    family = text("dicodePing_android/app/src/main/res/font/vazirmatn.xml")

    expected_gradle = (
        "abortOnError = true",
        "warningsAsErrors = false",
        "ignoreWarnings = false",
        'lintConfig = file("lint.xml")',
        "enableSplit = false",
    )
    for marker in expected_gradle:
        if marker not in gradle:
            errors.append(f"Missing stable lint/runtime marker: {marker}")

    for advisory in (
        "AndroidGradlePluginVersion",
        "GradleDependency",
        "UseKtx",
        "UnusedResources",
        "PluralsCandidate",
    ):
        if f'id="{advisory}" severity="ignore"' not in lint_policy:
            errors.append(f"Advisory lint scope is missing: {advisory}")

    if "android:enableOnBackInvokedCallback" in manifest:
        errors.append("API-33-only enableOnBackInvokedCallback remains in the base manifest")
    for marker in ("<queries>", "android.intent.category.LAUNCHER", "android:dataExtractionRules", "android:fullBackupContent"):
        if marker not in manifest:
            errors.append(f"Manifest compatibility marker is missing: {marker}")

    if "android:fontWeight" in family or "android:fontStyle" in family or "android:font=" in family:
        errors.append("Vazirmatn family still uses API-26-only android namespace attributes")
    for marker in ("app:fontWeight", "app:fontStyle", "app:font="):
        if marker not in family:
            errors.append(f"Vazirmatn support-library marker is missing: {marker}")
    for certs in (RES / "values/font_certs.xml", RES / "values-v26/font_certs.xml"):
        if certs.exists():
            errors.append(f"Obsolete downloadable-font certificate resource is still present: {certs.relative_to(ROOT)}")
    for family_file in (RES / "font").glob("*.xml"):
        body = family_file.read_text(encoding="utf-8-sig", errors="ignore")
        if "fontProvider" in body or "com_google_android_gms_fonts_certs" in body:
            errors.append(f"Downloadable-font provider resource is still present: {family_file.relative_to(ROOT)}")

    volume = text("dicodePing_android/app/src/main/java/ir/dicode/ping/net/VolumeDetector.kt")
    if 'String.format(Locale.US, "%.1f GB"' not in volume:
        errors.append("Volume formatting is not locale-stable")

    adapter = text("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/SourceAdapter.kt")
    if "DiffUtil.calculateDiff" not in adapter or "notifyDataSetChanged" in adapter:
        errors.append("SourceAdapter does not use precise DiffUtil updates")

    scanner = text("dicodePing_android/app/src/main/res/layout/fragment_scanner.xml")
    if 'tools:ignore="NestedScrolling"' not in scanner:
        errors.append("Intentional scanner log nesting is not scoped")
    item_source = text("dicodePing_android/app/src/main/res/layout/item_source.xml")
    if "MaterialSwitch" not in item_source or "<Switch" in item_source:
        errors.append("Platform Switch remains in item_source.xml")

    for layout in RES.glob("layout*/*.xml"):
        body = layout.read_text(encoding="utf-8-sig")
        if re.search(r'android:textSize="(?:[0-9]|10)sp"', body):
            errors.append(f"Sub-11sp text remains: {layout.relative_to(ROOT)}")

    expected_icons = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    hashes: set[bytes] = set()
    for density, size in expected_icons.items():
        icon = RES / f"mipmap-{density}/ic_launcher.png"
        if not icon.is_file():
            errors.append(f"Missing launcher icon: {icon.relative_to(ROOT)}")
            continue
        if png_size(icon) != (size, size):
            errors.append(f"Wrong launcher icon size for {density}: {png_size(icon)}")
        hashes.add(icon.read_bytes())
    if len(hashes) != len(expected_icons):
        errors.append("Launcher density assets are still byte-identical")

    strings = text("dicodePing_android/app/src/main/res/values/strings.xml")
    if re.search(r"\b[123]/3\b", strings):
        errors.append("Typography-fraction stage labels remain in English resources")

    localized_strings = text("dicodePing_android/app/src/main/res/values-fa/strings.xml")
    if 'translatable="false"' in localized_strings:
        errors.append("Persian resources duplicate non-translatable base constants")

    if not (RES / "xml/data_extraction_rules.xml").is_file() or not (RES / "xml/backup_rules.xml").is_file():
        errors.append("Backup/data extraction rules are incomplete")

    if errors:
        print("Android release validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Android release validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
