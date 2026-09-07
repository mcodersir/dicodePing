using Xunit;

namespace ServiceLib.Tests;

public class PoolNetworkTests
{
    private sealed class Capture : IProgress<PoolProgress>
    {
        public List<PoolProgress> Items { get; } = [];
        public void Report(PoolProgress value) => Items.Add(value);
    }

    [Fact]
    public async Task LocalReadinessDoesNotRequireGithub()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        try {
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            await PoolNetwork.WaitForListenerAsync(() => ((IPEndPoint)listener.LocalEndpoint).Port, deadline.Token);
        } finally { listener.Stop(); }
    }

    [Fact]
    public async Task SourceFailureRetriesThenUsesAnotherGithubEndpoint()
    {
        var calls = new List<string>();
        var progress = new Capture();
        var channels = await PoolNetwork.LoadChannelsAsync((url, _) => {
            calls.Add(url);
            return url.Contains("raw.githubusercontent.com")
                ? Task.FromException<string>(new HttpRequestException("unavailable"))
                : Task.FromResult("t.me/example_channel");
        }, progress, CancellationToken.None);
        Assert.Equal(3, calls.Count);
        Assert.Equal(["example_channel"], channels);
        Assert.All(progress.Items, item => Assert.Equal("کانال‌ها", item.Stage));
    }

    [Fact]
    public async Task SourceFailureIsNotReportedAsDisconnectedVpn()
    {
        var error = await Assert.ThrowsAsync<IOException>(() => PoolNetwork.LoadChannelsAsync(
            (_, _) => Task.FromException<string>(new HttpRequestException("network failure")), new Capture(), CancellationToken.None));
        Assert.Contains("فهرست کانال‌ها", error.Message);
        Assert.DoesNotContain("اتصال ساب پیش‌فرض برقرار نشد", error.Message);
    }

    [Fact]
    public async Task CancellationNeverRetriesOrReportsConnectionFailure()
    {
        using var cts = new CancellationTokenSource();
        cts.Cancel();
        var calls = 0;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => PoolNetwork.LoadChannelsAsync((_, _) => {
            calls++; return Task.FromResult("t.me/example_channel");
        }, new Capture(), cts.Token));
        Assert.Equal(0, calls);
    }
}
