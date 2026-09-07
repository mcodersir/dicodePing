using ServiceLib.Services;
using Xunit;

namespace ServiceLib.Tests;

public class ServerPoolTests
{
    [Theory]
    [InlineData(1, 899, 900, true)]
    [InlineData(10, -1, 20, false)]
    [InlineData(10, 901, 20, false)]
    [InlineData(0, 5, 10, false)]
    public void EverySampleMustPass(int a, int b, int c, bool accepted) =>
        Assert.Equal(accepted, ServerPoolService.AcceptSamples([a, b, c]));

    [Fact]
    public void MissingSamplesFail() => Assert.False(ServerPoolService.AcceptSamples([10, 20]));

    [Fact]
    public void ChannelsCannotInjectUrls() => Assert.Equal(["valid_channel"],
        ServerPoolService.ParseChannels("@valid_channel\nhttps://t.me/valid_channel\nt.me/valid_channel\nhttps://evil.example/x\n../foo\n# comment"));

    [Fact]
    public void TelegramProxiesAndUndatedPostsAreRejected()
    {
        var html = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-09-07T10:00:00Z\"></time>tg://proxy?server=x https://t.me/proxy?server=x</div>"
            + "<div class=\"tgme_widget_message_wrap\">vless://00000000-0000-0000-0000-000000000001@example.com:443</div>";
        Assert.Empty(ServerPoolService.ExtractLinks(html));
    }

    [Fact]
    public void FourRecentDistinctLinksAreDecoded()
    {
        var links = Enumerable.Range(1, 6).Select(i =>
            $"vless://00000000-0000-0000-0000-000000000001@server{i}.example:443?security=tls&amp;type=ws");
        var html = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-09-07T10:00:00Z\"></time>"
            + string.Join(" ", links) + "</div>";
        var result = ServerPoolService.ExtractLinks(html);
        Assert.Equal(4, result.Count);
        Assert.All(result, link => Assert.Contains("&type=ws", link));
    }

    [Fact]
    public void LatestAvailableLinksSurviveSevenDaysAndDeviceClockDifferences()
    {
        var link = "vless://00000000-0000-0000-0000-000000000001@example.com:443";
        var result = ServerPoolService.Inspect($"<div class=\"tgme_widget_message_wrap js-widget_message_wrap\"><code>{link}</code><time datetime=\"2026-08-30T04:42:53+00:00\">04:42</time></div>");
        Assert.Equal([link], result.Links);
        Assert.Contains("2026-08-30", result.Summary);
    }

    [Fact]
    public void AttributesEntitiesAndInlineFormattingAreHandled()
    {
        var html = "<div data-extra='x' class = 'other tgme_widget_message_wrap js-widget_message_wrap'><time datetime = '2026-08-30T04:42:53+00:00'></time>"
            + "<code>vless://00000000-0000-0000-0000-000000000001@<span>example.com</span>:443?security=tls&#38;type=ws</code><br>tg://proxy?server=x</div>";
        Assert.Equal(["vless://00000000-0000-0000-0000-000000000001@example.com:443?security=tls&type=ws"], ServerPoolService.ExtractLinks(html));
    }

    [Fact]
    public void UnavailablePagesHaveAnExplicitDiagnostic()
    {
        var result = ServerPoolService.Inspect("<html>Join Telegram</html>");
        Assert.Equal(0, result.Posts);
        Assert.Contains("دریافت نشد", result.Summary);
    }

    [Fact]
    public void ReleaseSmokeExtractsActualTelegramResponses()
    {
        var path = Environment.GetEnvironmentVariable("POOL_LIVE_FIXTURES");
        Assert.SkipWhen(path is null, "Live source check runs in release CI");
        var files = Directory.GetFiles(path!, "*.html");
        Assert.NotEmpty(files);
        var results = files.Select(file => ServerPoolService.Inspect(File.ReadAllText(file))).ToList();
        Assert.Contains(results, result => result.Links.Count > 0);
        Assert.All(results, result => Assert.InRange(result.Links.Count, 0, 4));
    }
}
