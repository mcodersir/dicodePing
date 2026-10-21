using Xunit;
using AwesomeAssertions;
using ServiceLib.Services;
namespace ServiceLib.Tests;
public class RemoteAdsTests
{
    private static string Config(string link, bool enabled = true) => JsonSerializer.Serialize(new {
        version = 1, enabled, placements = new { home = true, profiles = false },
        ads = new[] { new { enabled = true, placements = new[] { "home" }, title_fa = "حامی", title_en = "Sponsor", body_fa = "متن", body_en = "Text", target_url = link } }
    });
    [Theory]
    [InlineData("javascript:alert(1)")]
    [InlineData("http://example.com")]
    [InlineData("https://127.0.0.1/path")]
    [InlineData("https://user:pass@example.com")]
    public void UnsafeTargetsStayHidden(string link) => RemoteAds.Parse(Config(link), "home", true).Should().BeNull();
    [Fact]
    public void DisabledOrUnknownPlacementStaysHidden() {
        RemoteAds.Parse(Config("https://example.com", false), "home", true).Should().BeNull();
        RemoteAds.Parse(Config("https://example.com"), "profiles", true).Should().BeNull();
        RemoteAds.Parse("not json", "home", true).Should().BeNull();
    }
    [Fact]
    public void EnabledBannerUsesSelectedLanguage() {
        RemoteAds.Parse(Config("https://example.com"), "home", true)!.Title.Should().Be("حامی");
        RemoteAds.Parse(Config("https://example.com"), "home", false)!.Title.Should().Be("Sponsor");
    }
}
