from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read(path): return (ROOT/path).read_text('utf-8')

def test_android_splash_is_bounded_and_samples_thirty_percent():
    splash=read('dicodePing_android/app/src/main/java/ir/dicode/ping/SplashActivity.kt')
    repo=read('dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt')
    assert 'STARTUP_PIPELINE_TIMEOUT_MS = 38_000L' in splash
    assert 'STARTUP_SAMPLE_FRACTION = 0.30' in repo
    assert 'quickStartupProbe' in repo
    assert 'pingServers(servers.value)' not in repo.split('suspend fun initialize()',1)[1].split('fun refreshAll()',1)[0]

def test_scanner_has_review_output_tabs_and_cancellable_http():
    layout=read('dicodePing_android/app/src/main/res/layout/fragment_scanner.xml')
    fragment=read('dicodePing_android/app/src/main/java/ir/dicode/ping/ui/ScannerFragment.kt')
    crawler=read('dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt')
    assert 'scannerLogTabs' in layout and 'scannerLogText' in layout
    assert 'scanner_tab_review' in fragment and 'scanner_tab_output' in fragment
    assert 'suspendCancellableCoroutine' in crawler and 'call.cancel()' in crawler

def test_android_core_calls_are_process_serialized_and_apk_inventory_is_strict():
    bridge=read('dicodePing_android/app/src/main/java/ir/dicode/ping/xray/CoreBridge.kt')
    workflow=read('.github/workflows/v1.9.0-rc.12-release.yml')
    assert 'PROCESS_CORE_LOCK' in bridge
    assert 'verify_apk_cores.py' in workflow
    assert 'libgojni.so' in workflow and 'libaether.so' in workflow and 'libusque.so' in workflow
