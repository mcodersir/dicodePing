from __future__ import annotations

import argparse
import shutil
from pathlib import Path

FONT_SUFFIXES = {".ttf", ".otf", ".woff", ".woff2"}
LEGACY_ANDROID_FONT_RESOURCES = (
    Path("dicodePing_android/app/src/main/res/values/font_certs.xml"),
    Path("dicodePing_android/app/src/main/res/values-v26/font_certs.xml"),
)

GENERATED_NATIVE_FILES = {
    "core/xray.exe",
    "core/xray",
    "core/wintun.dll",
    "core/geoip.dat",
    "core/geosite.dat",
}

ANDROID_TETHERING_MAIN = Path(
    "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
)
ANDROID_TETHERING_STANDARD = Path(
    "dicodePing_android/app/src/standard/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
)
ANDROID_TETHERING_ROOTED = Path(
    "dicodePing_android/app/src/rooted/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
)


def clean(root: Path, *, clean_outputs: bool = True) -> list[Path]:
    removed: list[Path] = []

    assets = root / "assets"
    if assets.is_dir():
        for path in assets.rglob("*"):
            if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                path.unlink(missing_ok=True)
                removed.append(path)

    for relative in LEGACY_ANDROID_FONT_RESOURCES:
        path = root / relative
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(path)

    android_font_dir = root / "dicodePing_android/app/src/main/res/font"
    if android_font_dir.is_dir():
        for path in android_font_dir.glob("*.xml"):
            body = path.read_text(encoding="utf-8-sig", errors="ignore")
            if "fontProvider" in body or "com_google_android_gms_fonts_certs" in body:
                path.unlink(missing_ok=True)
                removed.append(path)

    for relative in GENERATED_NATIVE_FILES:
        path = root / relative
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(path)

    # Old RC folders may leave the same Kotlin class under src/main after a
    # newer ZIP is extracted over them. Product-flavor sources are compiled
    # together with main, so that stale copy causes a redeclaration. Delete it
    # only when both intended flavor implementations are present.
    main_controller = root / ANDROID_TETHERING_MAIN
    standard_controller = root / ANDROID_TETHERING_STANDARD
    rooted_controller = root / ANDROID_TETHERING_ROOTED
    if (
        main_controller.is_file()
        and standard_controller.is_file()
        and rooted_controller.is_file()
    ):
        main_controller.unlink()
        removed.append(main_controller)

    if clean_outputs:
        for relative in ("build", "dist"):
            path = root / relative
            if path.exists():
                shutil.rmtree(path)
                removed.append(path)

    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove stale files left by extracting a new source ZIP over an older workspace."
    )
    parser.add_argument("--keep-outputs", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    removed = clean(root, clean_outputs=not args.keep_outputs)
    if removed:
        print("Removed stale/generated workspace files:")
        for path in removed:
            print(f"  - {path.relative_to(root)}")
    else:
        print("Workspace is already clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
