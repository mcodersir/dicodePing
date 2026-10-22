using ServiceLib.Services;
using Xunit;

namespace ServiceLib.Tests.Services;
public class SmartConnectCandidatesTests
{
    [Fact]
    public void QuickSelectsBestOfFirstThreeSuccessfulDistinctProfiles()
    {
        var samples = new SmartConnectCandidates(3);
        Assert.Null(samples.BestId);
        Assert.False(samples.Add("failed", -1));
        Assert.False(samples.Add("first", 200));
        Assert.False(samples.Add("first", 150));
        Assert.False(samples.Add("second", 80));
        Assert.True(samples.Add("third", 100));
        Assert.True(samples.Add("late", 1));
        Assert.Equal("second", samples.BestId);
    }
    [Fact]
    public void BestIncludesLaterSamplesAndNeverSelectsFailedProfiles()
    {
        var samples = new SmartConnectCandidates(int.MaxValue);
        samples.Add("failed", 0);
        Assert.Null(samples.BestId);
        samples.Add("first", 100);
        samples.Add("later", 20);
        Assert.Equal("later", samples.BestId);
    }
}
