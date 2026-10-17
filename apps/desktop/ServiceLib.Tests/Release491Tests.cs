using ServiceLib.ViewModels;
using Xunit;

namespace ServiceLib.Tests;

public class Release491Tests
{
    [Fact]
    public async Task ASkippedProfileCannotKeepAnOldSuccessfulLatencyAfterAFreshScan()
    {
        var config = ServiceLib.Tests.CoreConfig.CoreConfigTestFactory.CreateConfig();
        ServiceLib.Tests.CoreConfig.CoreConfigTestFactory.BindAppManagerConfig(config);
        SQLiteHelper.Instance.CreateTable<ProfileItem>();
        var node = new ProfileItem { IndexId = "491-skipped-probe", ConfigType = EConfigType.Custom, CoreType = ECoreType.v2rayN };
        ProfileExManager.Instance.SetTestDelay(node.IndexId, 7);
        var service = new SpeedtestService(config, _ => Task.CompletedTask);
        var clear = typeof(SpeedtestService).GetMethod("GetClearItem", BindingFlags.Instance | BindingFlags.NonPublic)!;
        var result = await (Task<List<ServerTestItem>>)clear.Invoke(service, [ESpeedActionType.Realping, new List<ProfileItem> { node }])!;
        Assert.Empty(result);
        Assert.Equal(0, (await ProfileExManager.Instance.GetProfileExs()).Single(x => x.IndexId == node.IndexId).Delay);
    }

    private static T Uninitialized<T>() => (T)System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(typeof(T));

    [Fact]
    public async Task HomeDisconnectDoesNotConnectTheHighlightedProfile()
    {
        var model = Uninitialized<ProfilesViewModel>();
        model.IsConnectionRequested = () => true;
        var stops = 0; var starts = 0;
        model.StopConnection = () => { stops++; return Task.CompletedTask; };
        model.StartConnection = () => { starts++; return Task.CompletedTask; };
        // No config/row lookup is permitted while disconnecting the active session.
        await model.ConnectSelectedAsync();
        Assert.Equal(1, stops); Assert.Equal(0, starts);
    }

    [Fact]
    public async Task AQueuedRecoveryCannotUndoDisconnect()
    {
        var model = Uninitialized<MainWindowViewModel>();
        // The semaphore is deliberately absent: a stopped recovery must not even enter the queue.
        await model.Reload(forceStart: true);
        Assert.False(model.IsConnectionRequested);
    }

    [Fact]
    public async Task CancelledPoolRequestCannotSelectOrStartAnotherProfile()
    {
        var profiles = Uninitialized<ProfilesViewModel>();
        var main = Uninitialized<MainWindowViewModel>();
        typeof(MainWindowViewModel).GetField("<ProfilesViewModel>k__BackingField", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(main, profiles);
        await Assert.ThrowsAsync<OperationCanceledException>(() => main.ConnectPoolProfileAsync("ordinary-profile", CancellationToken.None, -1));
        Assert.False(main.IsConnectionRequested);
    }

    [Theory]
    [InlineData(204, "", true)]
    [InlineData(200, "<html>Sign in to network</html>", false)]
    [InlineData(302, "", false)]
    [InlineData(403, "blocked", false)]
    [InlineData(407, "proxy authentication", false)]
    [InlineData(500, "upstream failure", false)]
    public async Task RealPingValidatesTheResponseThroughItsExplicitProxy(int status, string body, bool expected)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var requests = 0;
        var server = Task.Run(async () => {
            try {
                while (!stop.IsCancellationRequested) {
                    using var connection = await listener.AcceptTcpClientAsync(stop.Token);
                    using var stream = connection.GetStream();
                    using var reader = new StreamReader(stream, leaveOpen: true);
                    var first = await reader.ReadLineAsync(stop.Token);
                    Assert.StartsWith("GET http://profile.invalid/generate_204", first);
                    while (!string.IsNullOrEmpty(await reader.ReadLineAsync(stop.Token))) { }
                    Interlocked.Increment(ref requests);
                    var response = $"HTTP/1.1 {status} Test\r\nContent-Length: {Encoding.UTF8.GetByteCount(body)}\r\nConnection: close\r\nLocation: http://direct.invalid/generate_204\r\n\r\n{body}";
                    await stream.WriteAsync(Encoding.UTF8.GetBytes(response), stop.Token);
                }
            } catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        });
        try {
            var proxy = new WebProxy($"http://127.0.0.1:{((IPEndPoint)listener.LocalEndpoint).Port}");
            var result = await ProxyHealthProbe.MeasureAsync("http://profile.invalid/generate_204", proxy, TimeSpan.FromSeconds(3));
            Assert.Equal(expected, result > 0);
            Assert.Equal(expected ? 2 : 1, requests);
        } finally { stop.Cancel(); await server; listener.Stop(); }
    }

    [Fact]
    public async Task RealPingNeverFallsBackToADirectRequest()
    {
        Assert.Equal(-1, await ProxyHealthProbe.MeasureAsync("https://www.google.com/generate_204", null, TimeSpan.FromSeconds(1)));
        var bypass = new WebProxy("http://127.0.0.1:1", false, [".*"]);
        Assert.Equal(-1, await ProxyHealthProbe.MeasureAsync("https://www.google.com/generate_204", bypass, TimeSpan.FromSeconds(1)));
    }
}
