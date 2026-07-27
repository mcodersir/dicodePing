from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_android_policy_test_matches_positive_real_latency_contract() -> None:
    policy = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/Models.kt")
    test = read("dicodePing_android/app/src/test/java/ir/dicode/ping/data/ServerPolicyTest.kt")
    assert "MIN_AUTO_PING_MS = 1" in policy
    assert "automaticModeAcceptsAnyPositiveVerifiedLatency" in test
    assert "assertTrue(ServerPolicy.isAutoEligible(server(69)))" in test
    assert "automaticModeRejectsSub70Latency" not in test


def test_android_warning_cleanup_and_node24_release_actions() -> None:
    gradle = read("dicodePing_android/app/build.gradle.kts")
    settings = read("dicodePing_android/app/src/main/java/ir/dicode/ping/ui/SettingsFragment.kt")
    locale = read("dicodePing_android/app/src/main/java/ir/dicode/ping/util/LocaleHelper.kt")
    workflow = read(".github/workflows/v1.9.0-rc.11-release.yml")
    assert '"**/libgojni.so"' in gradle
    assert 'Locale.forLanguageTag("fa")' in settings
    assert "Locale.forLanguageTag(language)" in locale
    for expected in (
        "actions/checkout@v6",
        "actions/setup-python@v6",
        "actions/setup-java@v5",
        "actions/setup-go@v6",
        "actions/upload-artifact@v7",
        "actions/download-artifact@v8",
        "gradle/actions/setup-gradle@v6",
        "softprops/action-gh-release@v3",
    ):
        assert expected in workflow
    assert "android-actions/setup-android" not in workflow


def test_scanner_and_auto_connect_use_resilient_candidate_pool() -> None:
    repo = read("dicodePing_android/app/src/main/java/ir/dicode/ping/data/AppRepository.kt")
    scanner = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerCoordinator.kt")
    activity = read("dicodePing_android/app/src/main/java/ir/dicode/ping/MainActivity.kt")
    service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/scanner/ScannerService.kt")
    assert "fun connectionCandidates(" in repo
    assert "DicodeVpnService validates each one with real" in repo
    assert "requireConnectedBootstrap()" in scanner
    assert "connectBootstrap()" not in scanner
    assert "vm.repo.connectionCandidates(AUTO_RETRY_LIMIT)" in activity
    assert "if (vm.repo.progress.value.active)" not in activity
    assert "runCatching { coordinator.join() }" in service
    assert "observeJob?.cancel()" in service
    assert "@Synchronized\n    private fun update(" in scanner


def test_android_crawler_has_bounded_call_and_response_memory() -> None:
    crawler = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt")
    assert "callTimeout(TIMEOUT_SECONDS + 5" in crawler
    assert "MAX_PREVIEW_BYTES" in crawler
    assert "source.buffer.clone().readUtf8" in crawler
