from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    constants = read("dicodeping/constants.py")
    gradle = read("dicodePing_android/app/build.gradle.kts")
    require('VERSION = "2.0.0"' in constants, "Desktop stable version is not 2.0.0", errors)
    require('RELEASE_VERSION = "2.0.0-rc.1"' in constants, "Desktop release version is not 2.0.0-rc.1", errors)
    require('versionCode = 55' in gradle, "Android versionCode 55 is missing", errors)
    require('versionName = "2.0.0-rc.1"' in gradle, "Android versionName is incorrect", errors)
    windows_meta = read("tools/windows_version_info.txt")
    require("filevers=(2, 0, 0, 1)" in windows_meta, "Windows fixed file version is incorrect", errors)
    require("prodvers=(2, 0, 0, 1)" in windows_meta, "Windows fixed product version is incorrect", errors)

    font_loader = read("dicodeping/font_loader.py")
    require("addApplicationFontFromData" in font_loader, "Desktop font is not registered from bundled bytes", errors)
    require("if IS_FROZEN:" in font_loader and "raise RuntimeError" in font_loader, "Frozen desktop package can silently fall back from Vazirmatn", errors)
    require(font_loader.count("Vazirmatn-") >= 3, "All required Vazirmatn weights are not declared", errors)

    font_prep = read("tools/prepare_vazirmatn.py")
    for marker in ("vazirmatn", 'VERSION = "33.0.3"', "sha512", "_verify_integrity", "--android"):
        require(marker in font_prep, f"Font preparation marker is missing: {marker}", errors)
    for builder in ("tools/build_windows.py", "tools/build_linux.py", "tools/build_macos.py"):
        body = read(builder)
        require("tools.prepare_vazirmatn" in body, f"{builder} does not prepare Vazirmatn", errors)
        require('app_v200_rc1.py' in body, f"{builder} does not package the 2.0 RC1 wrapper", errors)
        require('Vazirmatn-' in body, f"{builder} does not fail when font files are missing", errors)

    app = read("app.py")
    require("app.setFont(choose_persian_font())" in app, "Application-wide Vazirmatn font is not applied", errors)
    require('font-family: "Vazirmatn"' in app, "Application stylesheet does not enforce Vazirmatn", errors)
    require("font_family={app.font().family()}" in app, "Packaged smoke report does not expose the resolved font family", errors)

    android_sh = read("dicodePing_android/build_apk.sh")
    android_bat = read("dicodePing_android/build_apk.bat")
    require("prepare_vazirmatn.py --android" in android_sh, "Android shell build does not bundle Vazirmatn", errors)
    require("prepare_vazirmatn.py --android" in android_bat, "Android Windows build does not bundle Vazirmatn", errors)
    android_family = read("dicodePing_android/app/src/main/res/font/vazirmatn.xml")
    require("fontProvider" not in android_family, "Android still depends on an asynchronous downloadable font", errors)
    for weight in ("regular", "medium", "bold"):
        require(f"@font/vazirmatn_{weight}" in android_family, f"Android local Vazirmatn {weight} weight is missing", errors)

    scanner = read("dicodeping/scanner.py")
    require("def _recheck_saved_scanner_records" in scanner, "Desktop post-save scanner verification is missing", errors)
    require("tcp_ms = result.tcp_ms" in scanner, "Desktop post-save TCP ping is not persisted", errors)
    require("record.ping_ms = result.ping_ms" in scanner, "Desktop post-save Xray ping is not persisted", errors)
    require("force_geo=True" in scanner, "Desktop post-save location refresh is not forced", errors)
    require('post_save_verified_at' in scanner, "Desktop SUB transaction is not marked as reverified", errors)

    android_repo = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    require('"post_save_verify"' in android_repo, "Android post-save scanner verification stage is missing", errors)
    require("forceGeoRefresh = true" in android_repo, "Android post-save location refresh is not forced", errors)
    require('.put("postSaveVerified", true)' in android_repo, "Android final SUB transaction is not marked as reverified", errors)

    site = read("docs/site/index.html")
    require(not re.search(r"<(?:img|picture|source)\b", site, re.I), "Website contains screenshot/image markup", errors)
    require("screenshot" not in site.casefold(), "Website mentions screenshots", errors)
    require(site.count('class="card"') >= 6, "Website does not contain all platform download cards", errors)
    for asset in (
        "windows-x64.exe", "linux-x86_64.tar.gz", "macos-arm64.dmg",
        "macos-x86_64.dmg", "android.apk", "source.zip",
    ):
        require(asset in site, f"Website download link is missing: {asset}", errors)

    release = read(".github/workflows/release.yml")
    require("python tools/validate_v200_rc1.py" in release, "Release workflow does not run the 2.0 validator", errors)
    require(release.count("font_family=Vazirmatn") >= 3, "Release workflow does not validate Vazirmatn on all desktop packages", errors)
    require("v2.0.0-rc.1" in release, "Release workflow tag is incorrect", errors)

    docs = read(".github/workflows/docs.yml")
    for marker in ("actions/configure-pages@v5", "actions/upload-pages-artifact@v4", "actions/deploy-pages@v4"):
        require(marker in docs, f"GitHub Pages workflow marker missing: {marker}", errors)

    binary_fonts = list(ROOT.glob("assets/fonts/*.ttf")) + list(ROOT.glob("dicodePing_android/app/src/main/res/font/vazirmatn_*.ttf"))
    require(not binary_fonts, "Source snapshot contains generated font binaries", errors)

    if errors:
        print("2.0.0 RC1 validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("dicodePing 2.0.0 RC1 font, scanner, UI and Pages validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
