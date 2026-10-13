using Xunit;

namespace ServiceLib.Tests;

public class Release430RegressionTests
{
    [Fact]
    public async Task CancelledSubscriptionRefreshDoesNotAcquireOrLeakMutationGate()
    {
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => SubscriptionHandler.UpdateProcess(
            new Config(), "", false, (_, _) => Task.CompletedTask, cancelled.Token));
        Assert.Equal(1, ProfileOperationCoordinator.Gate.CurrentCount);
    }

    [Fact]
    public void LargeRunCountsUniqueResultsAndKeepsPartialCountWhenStopped()
    {
        var run = new ProbeRunModel { Total = 163, Name = "Latency" };
        for (var i = 0; i < 80; i++) { run.Complete(i.ToString()); run.Complete(i.ToString()); }
        Assert.Equal(80, run.Completed);
        Assert.InRange(run.Percent, 49, 50);
        run.StopRequested = true;
        run.UpdateSummary("Stopped");
        Assert.Contains("80 / 163", run.Summary);
        Assert.Contains("Stopped", run.Summary);
    }

    [Fact]
    public void DedupIgnoresSourceNamesButPreservesCredentialsAndTlsDifferences()
    {
        var a = new ProfileItem { IndexId = "1", Remarks = "Sponsor A", Subid = "a", ConfigType = EConfigType.VLESS, Address = "server", Port = 443, Password = "secret", StreamSecurity = "tls" };
        var b = new ProfileItem { IndexId = "2", Remarks = "Sponsor B", Subid = "b", ConfigType = EConfigType.VLESS, Address = "server", Port = 443, Password = "secret", StreamSecurity = "tls" };
        Assert.Equal(ConfigHandler.ConnectionIdentity(a), ConfigHandler.ConnectionIdentity(b));
        b.Password = "other";
        Assert.NotEqual(ConfigHandler.ConnectionIdentity(a), ConfigHandler.ConnectionIdentity(b));
        b.Password = "secret"; b.AllowInsecure = "true";
        Assert.NotEqual(ConfigHandler.ConnectionIdentity(a), ConfigHandler.ConnectionIdentity(b));
    }
}
