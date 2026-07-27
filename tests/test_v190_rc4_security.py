from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_source_zip_build_is_idempotent_and_cleans_stale_fonts() -> None:
    build = (ROOT / "BUILD_RELEASE_RC4.bat").read_text("utf-8")
    cleaner = (ROOT / "tools/prepare_build_workspace.py").read_text("utf-8")
    assert "tools\\prepare_build_workspace.py" in build
    assert 'FONT_SUFFIXES = {".ttf", ".otf", ".woff", ".woff2"}' in cleaner
    assert "path.suffix.lower()" in cleaner


def test_desktop_packages_follow_v180_rc4_style_and_only_apk_uses_owner_signing() -> None:
    windows = (ROOT / "tools/build_windows.py").read_text("utf-8")
    linux = (ROOT / "tools/build_linux.py").read_text("utf-8")
    macos = (ROOT / "tools/build_macos.py").read_text("utf-8")

    assert '"--onefile"' in windows
    assert '"--windowed"' in windows
    assert '"--uac-admin"' in windows
    assert "windows-x64.exe" in windows
    assert "DICODEPING_SIGN_" not in windows

    assert '"--onefile"' in linux
    assert "linux-{architecture}" in linux
    assert "DICODEPING_GPG_KEY_ID" not in linux

    assert '"--windowed"' in macos
    assert "macos-{architecture}" in macos
    assert ".dmg" in macos
    assert "notarytool" not in macos
    assert "codesign" not in macos


def test_xray_uses_locally_pinned_archive_digest() -> None:
    source = (ROOT / "dicodeping/xray.py").read_text("utf-8")
    assert "_XRAY_ARCHIVE_SHA256" in source
    ensure = source.split("def ensure_xray", 1)[1].split("def build_tun_config", 1)[0]
    assert ".dgst" not in ensure
    assert "_verify_sha256(archive, expected" in ensure


def test_android_standard_release_excludes_root_shell_code() -> None:
    gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text("utf-8")
    main_controller = ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/AndroidTetheringController.kt"
    standard = (ROOT / "dicodePing_android/app/src/standard/java/ir/dicode/ping/vpn/AndroidTetheringController.kt").read_text("utf-8")
    rooted = (ROOT / "dicodePing_android/app/src/rooted/java/ir/dicode/ping/vpn/AndroidTetheringController.kt").read_text("utf-8")
    manifest = (ROOT / "dicodePing_android/app/src/main/AndroidManifest.xml").read_text("utf-8")
    assert not main_controller.exists(), "common source-set controller causes flavor redeclaration"
    assert 'create("standard")' in gradle
    assert 'ENABLE_ROOT_TETHERING", "false"' in gradle
    assert "ProcessBuilder" not in standard
    assert "ProcessBuilder" in rooted
    assert 'android:allowBackup="false"' in manifest
    assert "CHANGE_NETWORK_STATE" not in manifest


def test_only_android_release_apk_builder_requires_owner_signing_key() -> None:
    root_builder = (ROOT / "BUILD_SIGNED_APK_RC6.bat").read_text("utf-8")
    apk_builder = (ROOT / "dicodePing_android/build_apk_rc6.bat").read_text("utf-8")
    debug_builder = (ROOT / "dicodePing_android/build_debug_apk.bat").read_text("utf-8")
    gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text("utf-8")

    assert "dicodePing_android\\build_apk_rc6.bat" in root_builder
    assert "ANDROID_KEYSTORE_PATH" in apk_builder
    assert ":app:assembleStandardRelease" in apk_builder
    assert "bundleStandardRelease" not in apk_builder
    assert ".aab" not in apk_builder.lower()
    assert "dicodePing-v1.9.0-rc.6-android.apk" in apk_builder
    assert ":app:assembleStandardDebug" in debug_builder
    assert "ANDROID_KEYSTORE_PATH" not in debug_builder
    assert 'signingConfigs.findByName("release")' in gradle


def test_ci_publishes_the_same_asset_shape_as_v180_rc4_plus_macos() -> None:
    workflow = (ROOT / ".github/workflows/v1.9.0-rc.6-release.yml").read_text("utf-8")
    shell_builder = (ROOT / "dicodePing_android/build_apk_rc6.sh").read_text("utf-8")

    assert "dicodePing-v1.9.0-rc.6-windows-x64.exe" in workflow
    assert "dicodePing-v1.9.0-rc.6-linux-x86_64.tar.gz" in workflow
    assert "dicodePing-v1.9.0-rc.6-macos-${{ matrix.architecture }}.dmg" in workflow
    assert "dicodePing-v1.9.0-rc.6-android.apk" in workflow
    assert "dicodePing-core-aether-1.4.0-windows-x64.zip" in workflow
    assert "dicodePing-core-usque-4.2.1-linux-x86_64.zip" in workflow
    assert "SHA256SUMS" in workflow
    assert "WINDOWS_SIGN_PFX" not in workflow
    assert "DICODEPING_GPG_KEY_ID" not in workflow
    assert "MACOS_CODESIGN_IDENTITY" not in workflow
    assert "bundleStandardRelease" not in workflow
    assert ".aab" not in workflow.lower()
    assert "dicodePing-v1.9.0-rc.6-android.apk" in shell_builder
