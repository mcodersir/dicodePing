using Xunit;

namespace ServiceLib.Tests;

public class Release493Tests
{
    [Fact]
    public void SavedLegacyDefaultStillUsesIndependentValidatedProviders() {
        Assert.Contains("https://detectportal.firefox.com/success.txt", ProxyHealthProbe.TargetsFor("http://www.google.com/generate_204"));
        Assert.True(ProxyHealthProbe.IsExpectedResponse(new Uri("https://detectportal.firefox.com/success.txt"), 200, "success\n"));
        Assert.False(ProxyHealthProbe.IsExpectedResponse(new Uri("https://detectportal.firefox.com/success.txt"), 200, "network login"));
    }
    [Fact]
    public void CustomDiagnosticStaysExactWhileBuiltInProvidersHaveFallbacks()
    {
        Assert.Equal(new[] { "http://127.0.0.1:9/generate_204" }, ProxyHealthProbe.TargetsFor("http://127.0.0.1:9/generate_204"));
        Assert.Contains("https://cp.cloudflare.com/generate_204", ProxyHealthProbe.TargetsFor("https://www.google.com/generate_204"));
    }

    [Fact]
    public void UpgradeDefaultsToPersianOnceAndPreservesTheNextUserChoice()
    {
        var ui = new UIItem { CurrentLanguage = "en" };
        ConfigHandler.ApplyPersianDefault(ui);
        Assert.Equal("fa", ui.CurrentLanguage);
        ui.CurrentLanguage = "en";
        ConfigHandler.ApplyPersianDefault(ui);
        Assert.Equal("en", ui.CurrentLanguage);
    }

    [Theory]
    [InlineData("{\"ip\":\"8.8.8.8\",\"country\":\"United States\",\"country_code\":\"US\"}", true)]
    [InlineData("{\"clientIp\":\"1.1.1.1\",\"country\":\"AU\"}", true)]
    [InlineData("{\"ip\":\"198.18.0.23\",\"country_code\":\"US\"}", false)]
    [InlineData("{\"ip\":\"localhost\",\"country_code\":\"US\"}", false)]
    [InlineData("<html>Sign in</html>", false)]
    public void LocationParsesDifferentProvidersAndRejectsFakeDns(string body, bool valid)
        => Assert.Equal(valid, ConnectionHandler.ParseIPInfo(body) is not null);

    [Fact]
    public async Task IndependentProviderSucceedsThroughTheSameProxyWhenTheFirstIsBlocked()
    {
        await WithProxy(async proxy => {
            var delay = await ProxyHealthProbe.MeasureAnyAsync(
                ["http://blocked.invalid/generate_204", "http://working.invalid/generate_204"], proxy, TimeSpan.FromSeconds(3));
            Assert.True(delay > 0);
            Assert.True(await ProxyThroughputProbe.MeasureAsync(
                ["http://blocked.invalid/file", "http://working.invalid/file"], proxy, TimeSpan.FromSeconds(2)) > 0);
        });
    }

    [Fact]
    public async Task FailedSecondSampleDoesNotEraseAValidatedFirstResponse()
    {
        await WithProxy(async proxy => Assert.True(await ProxyHealthProbe.MeasureAsync(
            "http://flaky.invalid/generate_204", proxy, TimeSpan.FromSeconds(3)) > 0));
    }

    [Fact]
    public async Task PortalCannotBecomeThroughputOrLatency()
    {
        await WithProxy(async proxy => {
            Assert.Equal(-1, await ProxyHealthProbe.MeasureAnyAsync(["http://portal.invalid/generate_204"], proxy, TimeSpan.FromSeconds(2)));
            Assert.Equal(0, await ProxyThroughputProbe.MeasureAsync(["http://portal.invalid/file"], proxy, TimeSpan.FromSeconds(2)));
        });
    }

    private static async Task WithProxy(Func<WebProxy, Task> run)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var flaky = 0;
        var workers = new List<Task>();
        var server = Task.Run(async () => {
            try {
                while (true) {
                    var socket = await listener.AcceptTcpClientAsync(stop.Token);
                    workers.Add(Task.Run(async () => {
                        using var owned = socket;
                        using var stream = socket.GetStream();
                        using var reader = new StreamReader(stream, leaveOpen: true);
                        var line = await reader.ReadLineAsync(stop.Token) ?? "";
                        while (!string.IsNullOrEmpty(await reader.ReadLineAsync(stop.Token))) { }
                        var portal = line.Contains("portal.invalid");
                        var failed = line.Contains("blocked.invalid") || (line.Contains("flaky.invalid") && Interlocked.Increment(ref flaky) > 1);
                        var file = line.Contains("/file");
                        var status = failed ? 403 : portal || file ? 200 : 204;
                        var payload = portal ? new string('x', 131072) : file && !failed ? new string('a', 262144) : "";
                        await stream.WriteAsync(Encoding.ASCII.GetBytes($"HTTP/1.1 {status} Test\r\nContent-Type: {(portal ? "text/html" : "application/octet-stream")}\r\nContent-Length: {payload.Length}\r\nConnection: close\r\n\r\n{payload}"), stop.Token);
                    }));
                }
            } catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        });
        try { await run(new WebProxy($"http://127.0.0.1:{((IPEndPoint)listener.LocalEndpoint).Port}")); }
        finally { stop.Cancel(); listener.Stop(); await server; await Task.WhenAll(workers); }
    }
}
