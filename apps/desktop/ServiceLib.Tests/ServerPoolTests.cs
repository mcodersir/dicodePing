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
    public void TelegramProxiesAndOldPostsAreRejected()
    {
        var html = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-09-07T10:00:00Z\"></time>tg://proxy?server=x https://t.me/proxy?server=x</div>"
            + "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-01-01T10:00:00Z\"></time>vless://00000000-0000-0000-0000-000000000001@example.com:443</div>";
        Assert.Empty(ServerPoolService.ExtractLinks(html, DateTimeOffset.Parse("2026-09-07T12:00:00Z")));
    }

    [Fact]
    public void FourRecentDistinctLinksAreDecoded()
    {
        var links = Enumerable.Range(1, 6).Select(i =>
            $"vless://00000000-0000-0000-0000-000000000001@server{i}.example:443?security=tls&amp;type=ws");
        var html = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-09-07T10:00:00Z\"></time>"
            + string.Join(" ", links) + "</div>";
        var result = ServerPoolService.ExtractLinks(html, DateTimeOffset.Parse("2026-09-07T12:00:00Z"));
        Assert.Equal(4, result.Count);
        Assert.All(result, link => Assert.Contains("&type=ws", link));
    }
}
