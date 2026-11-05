using ServiceLib.Services;
using Xunit;

namespace ServiceLib.Tests;

public class Release4998Tests
{
    [Theory]
    [InlineData(50_000_000_000L, 30_000_000_000L, 20_000_000_000L, 0.4)]
    [InlineData(50L, 80L, 0L, 0)]
    [InlineData(long.MaxValue, 0L, long.MaxValue, 1)]
    public void QuotaUsesProviderTotalAndClampsRemaining(long maximum, long remaining, long used, double fraction)
    {
        var quota = FoxQuota.From(maximum, remaining)!.Value;
        Assert.Equal(used, quota.Used);
        Assert.Equal(fraction, quota.Fraction, 6);
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData(0L, 0L)]
    [InlineData(-1L, 10L)]
    [InlineData(50L, -1L)]
    public void MissingAllowanceNeverFabricatesFiftyGigabytes(long? maximum, long? remaining) =>
        Assert.Null(FoxQuota.From(maximum, remaining));
}
