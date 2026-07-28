from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_android_xray_exposes_scanner_socks_inbound() -> None:
    builder = read("dicodePing_android/app/src/main/java/ir/dicode/ping/xray/XrayConfigBuilder.kt")
    assert "const val SCANNER_SOCKS_PORT = 18089" in builder
    assert '.put("tag", "scanner-socks")' in builder
    assert '.put("listen", "127.0.0.1")' in builder
    assert '.put("protocol", "socks")' in builder
    assert "JSONArray().put(tunInbound()).put(scannerSocksInbound())" in builder


def test_android_crawler_uses_xray_socks_and_proxy_dns() -> None:
    crawler = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt")
    assert "Proxy.Type.SOCKS" in crawler
    assert "XrayConfigBuilder.SCANNER_SOCKS_PORT" in crawler
    assert ".proxy(scannerProxy)" in crawler
    assert 'fetchUrl("https://t.me/s/$channel")' in crawler
    assert "telegram.me" not in crawler
    assert "Inet4Address" not in crawler


def test_android_crawler_does_not_abort_on_first_failed_channels() -> None:
    crawler = read("dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt")
    assert "val queue = ConcurrentLinkedQueue(channels)" in crawler
    assert "requireNotNull(preflight)" not in crawler
    assert "channels.take(4)" not in crawler
    assert "val current = done.incrementAndGet()" in crawler


def test_xray_app_uid_bypass_remains_for_loop_prevention() -> None:
    service = read("dicodePing_android/app/src/main/java/ir/dicode/ping/vpn/DicodeVpnService.kt")
    assert "builder.addDisallowedApplication(packageName)" in service
    assert "shouldBypassOwnPackage" not in service


def test_rc13_android_version_code_is_incremented() -> None:
    gradle = read("dicodePing_android/app/build.gradle.kts")
    assert 'versionName = "1.9.0-rc.13"' in gradle
    assert "versionCode = 48" in gradle
