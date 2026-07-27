from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_scanners_use_only_t_me_preview_endpoint() -> None:
    desktop = read("dicodeping/crawler.py")
    android = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt")
    assert 'https://t.me/s/{channel}' in desktop
    assert 'https://t.me/s/$channel' in android
    assert 'telegram.me' not in desktop
    assert 'telegram.me' not in android

def test_android_crawler_uses_bounded_fast_worker_queue() -> None:
    source = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt")
    assert "private const val MAX_WORKERS = 8" in source
    assert "ConcurrentLinkedQueue" in source
    assert "retryOnConnectionFailure(false)" in source
    assert "followRedirects(false)" in source
    assert "minimumChannelsBeforeTarget: Int = 36" in source

def test_android_scanner_progress_is_monotonic_and_target_aware() -> None:
    source = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    assert "plannedChannelBudget" in source
    assert "crawlFound" in source
    assert "maxOf(previous.progress" in source

def test_desktop_scanner_progress_is_phase_weighted() -> None:
    source = read("dicodeping/workers.py")
    assert "5 + (40 * max(0, done) // max(1, total))" in source
    assert "50 + (45 * max(0, done) // max(1, total))" in source

def test_rc12_release_files_exist() -> None:
    assert (ROOT / "DEPLOY_PRERELEASE_RC12.bat").is_file()
    assert (ROOT / ".github/workflows/v1.9.0-rc.12-release.yml").is_file()
    assert (ROOT / "docs/releases/v1.9.0-rc.12.md").is_file()
