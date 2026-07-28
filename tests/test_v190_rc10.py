from __future__ import annotations

from pathlib import Path

import dicodeping.crawler as crawler

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_channel_fetch_prefers_socks_and_uses_t_me_only(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_fetch(url: str, *, timeout: float, socks_port: int):
        calls.append((url, socks_port))
        page = '<div class="tgme_widget_message">vless://id@example.test:443</div>'
        return page, len(page), "socks5"

    monkeypatch.setattr(crawler, "_fetch_url_payload", fake_fetch)
    result = crawler.fetch_channel("demo", per_channel_limit=8, socks_port=1819)
    assert result.ok
    assert result.transport == "socks5"
    assert result.picked == 1
    assert calls == [("https://t.me/s/demo", 1819)]


def test_desktop_route_preflight_returns_first_usable_channel(monkeypatch) -> None:
    visited: list[str] = []

    def fake_channel(channel: str, **_kwargs):
        visited.append(channel)
        return crawler.ChannelResult(
            channel, channel == "second", 1 if channel == "second" else 0,
            1 if channel == "second" else 0, 10,
            ["vless://id@example.test:443"] if channel == "second" else [],
            error="failed" if channel != "second" else "",
            transport="socks5",
        )

    monkeypatch.setattr(crawler, "fetch_channel", fake_channel)
    result = crawler.verify_telegram_route(["first", "second", "third"], socks_port=1819)
    assert result.ok
    assert result.channel == "second"
    assert visited == ["first", "second"]


def test_scanner_ui_advances_after_verified_vpn_connection() -> None:
    source = (ROOT / "dicodeping/ui.py").read_text("utf-8")
    assert "VPN متصل شد؛ دریافت کانفیگ از تلگرام شروع شد" in source
    assert "توقف اسکن — دریافت تلگرام" in source
    assert "scanner.notify_connection_result(True)" in source


def test_android_crawler_is_bounded_and_reports_each_result() -> None:
    source = (ROOT / "dicodePing_android/app/src/main/java/ir/dicode/ping/net/TelegramChannelCrawler.kt").read_text("utf-8")
    assert "maxRequests = MAX_WORKERS" in source
    assert "maxRequestsPerHost = MAX_WORKERS" in source
    assert "private const val MAX_WORKERS = 8" in source
    assert "onResult: ((ChannelResult, Int, Int) -> Unit)?" in source
    assert 'fetchUrl("https://t.me/s/$channel")' in source
    assert "telegram.me" not in source


def test_rc13_release_metadata_and_workflow_exist() -> None:
    assert (ROOT / "DEPLOY_PRERELEASE_RC13.bat").is_file()
    assert (ROOT / ".github/workflows/v1.9.0-rc.13-release.yml").is_file()
    assert (ROOT / "docs/releases/v1.9.0-rc.13.md").is_file()
    constants = (ROOT / "dicodeping/constants.py").read_text("utf-8")
    gradle = (ROOT / "dicodePing_android/app/build.gradle.kts").read_text("utf-8")
    assert 'RELEASE_VERSION = "1.9.0-rc.13"' in constants
    assert 'versionName = "1.9.0-rc.13"' in gradle
    assert "versionCode = 48" in gradle
