from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def text(path): return (ROOT/path).read_text(encoding="utf-8")

def test_version_and_android_code():
    assert 'RELEASE_VERSION = "1.9.0-rc.18"' in text('dicodeping/constants.py')
    gradle=text('dicodePing_android/app/build.gradle.kts')
    assert 'versionCode = 53' in gradle
    assert 'versionName = "1.9.0-rc.18"' in gradle

def test_settings_no_duplicate_app_bypass_and_no_wrong_cdn_id():
    layout=text('dicodePing_android/app/src/main/res/layout/fragment_settings.xml')
    assert 'chooseBypassApps' not in layout
    assert layout.count('android:id="@+id/cdnDomainLayout"') == 1
    assert 'app:hintEnabled="false"' in layout

def test_server_metadata_badges_are_independent():
    layout=text('dicodePing_android/app/src/main/res/layout/item_server.xml')
    assert 'qualityVolume' not in layout
    for item in ('qualityBadge','profileBadge','volumeBadge'):
        assert item in layout

def test_scanner_progress_is_split():
    layout=text('dicodePing_android/app/src/main/res/layout/fragment_scanner.xml')
    assert 'scannerFetchProgress' in layout
    assert 'scannerTestProgress' in layout
    assert 'scannerProgressBar' not in layout

def test_usque_uses_supported_config_flag():
    desktop=text('dicodeping/connection_manager.py')
    android=text('dicodePing_android/app/src/main/java/ir/dicode/ping/core/ExternalCoreCommandBuilder.kt')
    process=text('dicodePing_android/app/src/main/java/ir/dicode/ping/core/AndroidExternalCoreProcess.kt')
    assert '"-c", str(config)' in desktop
    assert 'command.append("--http2")' in desktop
    assert desktop.index('"socks"') < desktop.index('command.append("--http2")')
    assert '"-c", config' in android
    assert 'ExternalCoreCommandBuilder.registration' in process

def test_pages_workflow_versions_and_shape():
    docs=text('.github/workflows/docs.yml')
    assert 'actions/upload-pages-artifact@v4' in docs
    assert 'actions/deploy-pages@v4' in docs
    assert 'needs: build' in docs
