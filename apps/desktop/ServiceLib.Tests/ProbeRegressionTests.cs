using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class ProbeRegressionTests
{
    [Fact]
    public void BuiltInSubscriptionMigrationIsIdempotentAndPreservesUserLinks()
    {
        var item = new SubItem { Id = "existing", Enabled = false, MoreUrl = "https://example.com/sub," + DicodePingBootstrap.SecondarySubscriptionUrl };
        DicodePingBootstrap.ConfigurePrimarySubscription(item);
        DicodePingBootstrap.ConfigurePrimarySubscription(item);
        Assert.Equal("existing", item.Id);
        Assert.False(item.Enabled);
        Assert.Equal("Dicode Config Checker", item.Remarks);
        Assert.Equal(DicodePingBootstrap.DefaultSubscriptionUrl, item.Url);
        Assert.Equal("https://example.com/sub," + DicodePingBootstrap.SecondarySubscriptionUrl, item.MoreUrl);
    }

    [Fact]
    public async Task CancellingOneProbeInstanceDoesNotStopAnotherInstance()
    {
        var config = CoreConfigTestFactory.CreateConfig();
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var reached = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var running = new SpeedtestService(config, async result =>
        {
            if (result.Delay == ResUI.SpeedtestingCompleted) { reached.TrySetResult(); await release.Task; }
        });
        var other = new SpeedtestService(config, _ => Task.CompletedTask);
        var task = running.RunLoop(ESpeedActionType.Realping, []);
        await reached.Task.WaitAsync(TimeSpan.FromSeconds(5));
        other.ExitLoop();
        Assert.False(task.IsCompleted);
        release.TrySetResult();
        await task.WaitAsync(TimeSpan.FromSeconds(5));
        // An already completed run can be stopped and rerun without retaining a disposed CTS.
        running.ExitLoop();
        await running.RunLoop(ESpeedActionType.Realping, []).WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task CancellationPropagatesThroughHttpProbe()
    {
        var config = CoreConfigTestFactory.CreateConfig();
        CoreConfigTestFactory.BindAppManagerConfig(config);
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => ConnectionHandler.GetRealPingTime(null, cancellation.Token));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new DownloadService().TryDownloadString("http://127.0.0.1:1/", (IWebProxy?)null, "", cancellation.Token));
    }
}
