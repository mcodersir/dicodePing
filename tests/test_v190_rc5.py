from pathlib import Path

from dicodeping.scanner import generate_sub_name
from dicodeping.sources import normalize_sources


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rc5_release_metadata_and_deployer_are_consistent() -> None:
    assert 'RELEASE_VERSION = "1.9.0-rc.11"' in read("dicodeping/constants.py")
    assert '__version__ = "1.9.0rc11"' in read("dicodeping/__init__.py")
    deploy = read("DEPLOY_PRERELEASE_RC11.bat")
    assert "v1.9.0-rc.11" in deploy
    assert "v1.9.0-rc.11-release.yml" in deploy
    assert "wait_for_github_release_rc11.ps1" in deploy


def test_scanner_always_updates_one_copyable_sub() -> None:
    assert generate_sub_name(None) == "SUB"
    assert generate_sub_name("anything") == "SUB"
    scanner = read("dicodeping/scanner.py")
    assert 'SCANNER_SOURCE_ID = "scanner-sub"' in scanner
    assert 'SCANNER_SOURCE_NAME = "SUB"' in scanner
    assert "history = [history_record]" in scanner
    assert "save_scanner_transaction(" in scanner
    assert 'SCANNER_EXPORT_DIR / f"{source_id}.txt"' in scanner
    assert 'SCANNER_EXPORT_DIR / f"{source_id}.base64.txt"' in scanner


def test_local_scanner_source_survives_source_normalization() -> None:
    normalized = normalize_sources({
        "sources": [{"id": "scanner-sub", "name": "SUB", "url": "", "order": 9, "enabled": True}]
    })
    scanner = next(item for item in normalized if item.id == "scanner-sub")
    assert scanner.name == "SUB"
    assert scanner.url == ""


def test_bootstrap_wait_is_event_driven_and_not_the_old_20_second_poll() -> None:
    scanner = read("dicodeping/scanner.py")
    workers = read("dicodeping/workers.py")
    assert "SCAN_BOOTSTRAP_CONNECT_TIMEOUT_S = 55.0" in scanner
    assert "wait_connected_callback" in scanner
    assert "wait_disconnected_callback" in scanner
    assert "notify_connection_result" in workers
    assert "notify_disconnected" in workers
    assert "wait_for_connection" in workers
    assert "wait_for_disconnect" in workers
    assert "did not reach the connected state in 20 seconds" not in scanner


def test_desktop_scanner_layout_and_disconnect_lifecycle_are_safe() -> None:
    ui = read("dicodeping/ui.py")
    rc2 = read("dicodeping/rc2_runtime.py")
    rc7 = read("dicodeping/rc6_runtime.py")
    assert "QPlainTextEdit.LineWrapMode.WidgetWidth" in ui
    failed_block = ui[ui.index("def connect_failed"):ui.index("def _continue_auto_connect")]
    assert "self.manager.stop()" not in failed_block
    assert "thread.finished.connect(finish)" in rc2
    assert "requestInterruption()" in rc7
    assert "worker.finished.connect" in rc7
    assert "scanner.finished.connect" in rc7
    assert "monitor.finished.connect" in rc7
    assert ".terminate()" not in rc7


def test_sidebar_alignment_tracks_layout_direction() -> None:
    ui = read("dicodeping/ui.py")
    assert "def _apply_button_alignment" in ui
    assert "Qt.RightToLeft if self.window.is_rtl else Qt.LeftToRight" in ui
    assert 'alignment = "right" if self.window.is_rtl else "left"' in ui


def test_android_rc5_is_api36_64_bit_and_serializes_native_core() -> None:
    gradle = read("dicodePing_android/app/build.gradle.kts")
    bridge = read("dicodePing_android/app/src/main/java/ir/dicode/ping/xray/CoreBridge.kt")
    root_gradle = read("dicodePing_android/build.gradle.kts")
    wrapper = read("dicodePing_android/gradle/wrapper/gradle-wrapper.properties")
    assert "compileSdk = 36" in gradle
    assert "targetSdk = 36" in gradle
    assert "versionCode = 46" in gradle
    assert 'versionName = "1.9.0-rc.11"' in gradle
    assert 'setOf("arm64-v8a", "x86_64")' in gradle
    assert "jniLibs.useLegacyPackaging = true" in gradle
    assert 'com.android.tools.build:gradle:8.10.1' in root_gradle
    assert "gradle-8.11.1-bin.zip" in wrapper
    assert bridge.count("@Synchronized") >= 4


def test_android_core_validation_regex_is_valid_kotlin_dsl() -> None:
    gradle = read("dicodePing_android/app/build.gradle.kts")
    validator = read("tools/validate_android_gradle_kts.py")
    deploy = read("DEPLOY_PRERELEASE_RC11.bat")
    workflow = read(".github/workflows/v1.9.0-rc.11-release.yml")
    assert 'Regex("""jni/.+/(libgojni|libv2ray)\\.so""")' in gradle
    assert 'Regex("jni/.+/(libgojni|libv2ray)\\.so")' not in gradle
    assert "Android Gradle Kotlin DSL regex validation passed" in validator
    assert "validate_android_gradle_kts.py" in deploy
    assert workflow.count("validate_android_gradle_kts.py") == 2


def test_android_flavors_do_not_redeclare_tethering_controller() -> None:
    controllers = list((ROOT / "dicodePing_android/app/src").rglob("AndroidTetheringController.kt"))
    relative = {path.relative_to(ROOT).as_posix() for path in controllers}
    assert "dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/AndroidTetheringController.kt" not in relative
    assert "dicodePing_android/app/src/standard/java/ir/dicode/ping/vpn/AndroidTetheringController.kt" in relative
    assert "dicodePing_android/app/src/rooted/java/ir/dicode/ping/vpn/AndroidTetheringController.kt" in relative


def test_release_workflow_verifies_android_native_packaging() -> None:
    workflow = read(".github/workflows/v1.9.0-rc.11-release.yml")
    assert '"$zipalign_bin" -c -P 16 -v 4 "$apk"' in workflow
    assert "armeabi-v7a|x86" in workflow
    assert "lib/arm64-v8a/" in workflow
    assert "lib/x86_64/" in workflow
    assert "dicodePing-v1.9.0-rc.11-android.apk" in workflow
    assert "dicodePing-v1.9.0-rc.11-macos-${{ matrix.architecture }}.dmg" in workflow
    assert "architecture: arm64" in workflow
    assert "architecture: x86_64" in workflow
